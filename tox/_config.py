import argparse
import distutils.sysconfig
import os
import sys
import re
import shlex
import string
import subprocess
import textwrap

import py

import tox

defaultenvs = {'jython': 'jython', 'pypy': 'pypy'}
for _name in "py,py24,py25,py26,py27,py30,py31,py32,py33,py34".split(","):
    if _name == "py":
        basepython = sys.executable
    else:
        basepython = "python" + ".".join(_name[2:4])
    defaultenvs[_name] = basepython

def parseconfig(args=None, pkg=None):
    if args is None:
        args = sys.argv[1:]
    parser = prepare_parse(pkg)
    opts = parser.parse_args(args)
    config = Config()
    config.option = opts
    basename = config.option.configfile
    if os.path.isabs(basename):
        inipath = py.path.local(basename)
    else:
        for path in py.path.local().parts(reverse=True):
            inipath = path.join(basename)
            if inipath.check():
                break
        else:
            feedback("toxini file %r not found" %(basename), sysexit=True)
    try:
        parseini(config, inipath)
    except tox.exception.InterpreterNotFound:
        exn = sys.exc_info()[1]
        # Use stdout to match test expectations
        py.builtin.print_("ERROR: " + str(exn))
    return config

def feedback(msg, sysexit=False):
    py.builtin.print_("ERROR: " + msg, file=sys.stderr)
    if sysexit:
        raise SystemExit(1)

class VersionAction(argparse.Action):
    def __call__(self, argparser, *args, **kwargs):
        name = argparser.pkgname
        mod = __import__(name)
        version = mod.__version__
        py.builtin.print_("%s imported from %s" %(version, mod.__file__))
        raise SystemExit(0)

class CountAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if hasattr(namespace, self.dest):
            setattr(namespace, self.dest, int(getattr(namespace, self.dest))+1)
        else:
            setattr(namespace, self.dest, 0)

def prepare_parse(pkgname):
    parser = argparse.ArgumentParser(description=__doc__,)
        #formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.pkgname = pkgname
    parser.add_argument("--version", nargs=0, action=VersionAction,
        dest="version",
        help="report version information to stdout.")
    parser.add_argument("-v", nargs=0, action=CountAction, default=0,
        dest="verbosity",
        help="increase verbosity of reporting output.")
    parser.add_argument("--showconfig", action="store_true", dest="showconfig",
        help="show configuration information. ")
    parser.add_argument("-c", action="store", default="tox.ini",
        dest="configfile",
        help="use the specified config file name.")
    parser.add_argument("-e", action="store", dest="env",
        metavar="envlist",
        help="work against specified environments (ALL selects all).")
    parser.add_argument("--notest", action="store_true", dest="notest",
        help="skip invoking test commands.")
    parser.add_argument("--sdistonly", action="store_true", dest="sdistonly",
        help="only perform the sdist packaging activity.")
    parser.add_argument("--installpkg", action="store", default=None,
        help="use specified package for installation into venv")
    parser.add_argument('-i', action="append",
        dest="indexurl", metavar="URL",
        help="set indexserver url (if URL is of form name=url set the "
        "url for the 'name' indexserver, specifically)")
    parser.add_argument("-r", "--recreate", action="store_true",
        dest="recreate",
        help="force recreation of virtual environments")
    parser.add_argument("--extradeps", action="store", default="",
        help="comma-separated list of global extra dependencies")
    parser.add_argument("args", nargs="*",
        help="additional arguments available to command positional substition")
    return parser

class Config:
    def __init__(self):
        self.envconfigs = {}
        self.invocationcwd = py.path.local()

class VenvConfig:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def envbindir(self):
        if sys.platform == "win32" and "jython" not in self.basepython:
            return self.envdir.join("Scripts")
        else:
            return self.envdir.join("bin")

    @property
    def envpython(self):
        if "jython" in str(self.basepython):
            name = "jython"
        else:
            name = "python"
        return self.envbindir.join(name)

    def envsitepackagesdir(self):
        print_envsitepackagesdir = textwrap.dedent("""
        import sys
        from distutils.sysconfig import get_python_lib
        sys.stdout.write(get_python_lib(prefix=sys.argv[1]))
        """)

        exe = self.getsupportedinterpreter()
        # can't use check_output until py27
        proc = subprocess.Popen(
            [str(exe), '-c', print_envsitepackagesdir, str(self.envdir)],
            stdout=subprocess.PIPE)
        odata, edata = proc.communicate()
        if proc.returncode:
            raise tox.exception.UnsupportedInterpreter(
                "Error getting site-packages from %s" % self.basepython)
        return odata

    def getconfigexecutable(self):
        from tox._venv import find_executable

        python = self.basepython
        if not python:
            python = sys.executable
        x = find_executable(str(python))
        if x:
            x = x.realpath()
        return x

    def getsupportedinterpreter(self):
        if sys.platform == "win32" and self.basepython and \
                "jython" in self.basepython:
            raise tox.exception.UnsupportedInterpreter(
                "Jython/Windows does not support installing scripts")
        config_executable = self.getconfigexecutable()
        if not config_executable:
            raise tox.exception.InterpreterNotFound(self.basepython)
        return config_executable
testenvprefix = "testenv:"

class parseini:
    def __init__(self, config, inipath):
        config.toxinipath = inipath
        config.toxinidir = toxinidir = config.toxinipath.dirpath()

        self._cfg = py.iniconfig.IniConfig(config.toxinipath)
        config._cfg = self._cfg
        self.config = config
        ctxname = getcontextname()
        if ctxname == "jenkins":
            reader = IniReader(self._cfg, fallbacksections=['tox'])
            toxsection = "tox:%s" % ctxname
            distshare_default = "{toxworkdir}/distshare"
        elif not ctxname:
            reader = IniReader(self._cfg)
            toxsection = "tox"
            distshare_default = "{homedir}/.tox/distshare"
        else:
            raise ValueError("invalid context")

        config.homedir = py.path.local._gethomedir()
        reader.addsubstitions(toxinidir=config.toxinidir,
                              homedir=config.homedir)
        config.toxworkdir = reader.getpath(toxsection, "toxworkdir",
                                           "{toxinidir}/.tox")
        config.minversion = reader.getdefault(toxsection, "minversion", None)

        # determine indexserver dictionary
        config.indexserver = {'default': IndexServerConfig('default')}
        prefix = "indexserver"
        for line in reader.getlist(toxsection, "indexserver"):
            name, url = map(lambda x: x.strip(), line.split("=", 1))
            config.indexserver[name] = IndexServerConfig(name, url)

        override = False
        if config.option.indexurl:
            for urldef in config.option.indexurl:
                m = re.match(r"\W*(\w+)=(\S+)", urldef)
                if m is None:
                    url = urldef
                    name = "default"
                else:
                    name, url = m.groups()
                    if not url:
                        url = None
                if name != "ALL":
                    config.indexserver[name].url = url
                else:
                    override = url
        # let ALL override all existing entries
        if override:
            for name in config.indexserver:
                config.indexserver[name] = IndexServerConfig(name, override)

        reader.addsubstitions(toxworkdir=config.toxworkdir)
        config.distdir = reader.getpath(toxsection, "distdir",
                                           "{toxworkdir}/dist")
        reader.addsubstitions(distdir=config.distdir)
        config.distshare = reader.getpath(toxsection, "distshare",
                                          distshare_default)
        reader.addsubstitions(distshare=config.distshare)
        config.sdistsrc = reader.getpath(toxsection, "sdistsrc", None)
        config.setupdir = reader.getpath(toxsection, "setupdir", "{toxinidir}")
        config.logdir = config.toxworkdir.join("log")
        for sectionwrapper in self._cfg:
            section = sectionwrapper.name
            if section.startswith(testenvprefix):
                name = section[len(testenvprefix):]
                envconfig = self._makeenvconfig(name, section, reader._subs,
                    config)
                config.envconfigs[name] = envconfig
        if not config.envconfigs:
            config.envconfigs['python'] = \
                self._makeenvconfig("python", "_xz_9", reader._subs, config)
        config.envlist = self._getenvlist(reader, toxsection)
        for name in config.envlist:
            if name not in config.envconfigs:
                if name in defaultenvs:
                    config.envconfigs[name] = \
                self._makeenvconfig(name, "_xz_9", reader._subs, config)

    def _makeenvconfig(self, name, section, subs, config):
        vc = VenvConfig(envname=name)
        vc.config = config
        reader = IniReader(self._cfg, fallbacksections=["testenv"])
        reader.addsubstitions(**subs)
        vc.envdir = reader.getpath(section, "envdir", "{toxworkdir}/%s" % name)
        vc.args_are_paths = reader.getbool(section, "args_are_paths", True)
        if reader.getdefault(section, "python", None):
            raise tox.exception.ConfigError(
                "'python=' key was renamed to 'basepython='")
        if name in defaultenvs:
            bp = defaultenvs[name]
        else:
            bp = sys.executable
        vc.basepython = reader.getdefault(section, "basepython", bp)
        reader.addsubstitions(envdir=vc.envdir, envname=vc.envname,
                              envbindir=vc.envbindir, envpython=vc.envpython,
                              envsitepackagesdir=vc.envsitepackagesdir)
        vc.envtmpdir = reader.getpath(section, "tmpdir", "{envdir}/tmp")
        vc.envlogdir = reader.getpath(section, "envlogdir", "{envdir}/log")
        reader.addsubstitions(envlogdir=vc.envlogdir, envtmpdir=vc.envtmpdir)
        vc.changedir = reader.getpath(section, "changedir", "{toxinidir}")
        if config.option.recreate:
            vc.recreate = True
        else:
            vc.recreate = reader.getbool(section, "recreate", False)
        args = config.option.args
        if args:
            if vc.args_are_paths:
                args = []
                for arg in config.option.args:
                    origpath = config.invocationcwd.join(arg, abs=True)
                    if origpath.check():
                        arg = vc.changedir.bestrelpath(origpath)
                    args.append(arg)
            reader.addsubstitions(args)
        vc.setenv = reader.getdict(section, 'setenv')
        if not vc.setenv:
            vc.setenv = None

        vc.commands = reader.getargvlist(section, "commands")
        vc.deps = []
        deplines = reader.getlist(section, "deps")
        deplines.extend(filter(None, config.option.extradeps.split(",")))
        for depline in deplines:
            m = re.match(r":(\w+):\s*(\S+)", depline)
            if m:
                iname, name = m.groups()
                ixserver = config.indexserver[iname]
            else:
                name = depline.strip()
                ixserver = None
            vc.deps.append(DepConfig(name, ixserver))
        vc.distribute = reader.getbool(section, "distribute", True)
        vc.sitepackages = reader.getbool(section, "sitepackages", False)
        downloadcache = reader.getdefault(section, "downloadcache")
        if downloadcache is None:
            downloadcache = os.environ.get("PIP_DOWNLOAD_CACHE", "")
            if not downloadcache:
                downloadcache = self.config.toxworkdir.join("_download")
        vc.downloadcache = py.path.local(downloadcache)
        return vc

    def _getenvlist(self, reader, toxsection):
        env = self.config.option.env
        if not env:
            env = os.environ.get("TOXENV", None)
            if not env:
                envlist = reader.getlist(toxsection, "envlist", sep=",")
                if not envlist:
                    envlist = self.config.envconfigs.keys()
                return envlist
        if env == "ALL":
            envlist = list(self.config.envconfigs)
            envlist.sort()
        else:
            envlist = env.split(",")
        return envlist

class DepConfig:
    def __init__(self, name, indexserver=None):
        self.name = name
        self.indexserver = indexserver

    def __str__(self):
        if self.indexserver:
            if self.indexserver.name == "default":
               return self.name
            return ":%s:%s" %(self.indexserver.name, self.name)
        return str(self.name)
    __repr__ = __str__

class IndexServerConfig:
    def __init__(self, name, url=None):
        self.name = name
        self.url = url

class IniReader:
    def __init__(self, cfgparser, fallbacksections=None):
        self._cfg = cfgparser
        self.fallbacksections = fallbacksections or []
        self._subs = {}
        self._subststack = []

    def addsubstitions(self, _posargs=None, **kw):
        self._subs.update(kw)
        if _posargs:
            self._subs['_posargs'] = _posargs

    def getpath(self, section, name, defaultpath):
        toxinidir = self._subs['toxinidir']
        path = self.getdefault(section, name, defaultpath)
        if path is None:
            return path
        return toxinidir.join(path, abs=True)

    def getlist(self, section, name, sep="\n"):
        s = self.getdefault(section, name, None)
        if s is None:
            return []
        return [x.strip() for x in s.split(sep) if x.strip()]

    def getdict(self, section, name, sep="\n"):
        s = self.getdefault(section, name, None)
        if s is None:
            return {}

        value = {}
        for line in s.split(sep):
            name, rest = line.split('=', 1)
            value[name.strip()] = rest.strip()

        return value

    def getargvlist(self, section, name):
        s = self.getdefault(section, name, '', replace=False)
        #if s is None:
        #    raise tox.exception.ConfigError(
        #        "no command list %r defined in section [%s]" %(name, section))
        commandlist = []
        current_command = ""
        for line in s.split("\n"):
            line = line.rstrip()
            i = line.find("#")
            if i != -1:
                line = line[:i].rstrip()
            if not line:
                continue
            if line.endswith("\\"):
                current_command += " " + line[:-1]
                continue
            current_command += line
            commandlist.append(self._processcommand(current_command))
            current_command = ""
        else:
            if current_command:
                raise tox.exception.ConfigError(
                    "line-continuation for [%s] %s ends nowhere" %
                    (section, name))
        return commandlist

    def _processcommand(self, command):
        posargs = self._subs.get('_posargs', None)
        pat = r'\{(?:(?P<sub_type>[^:]+):)?(?P<substitution_value>.*)\}'
        words = list(CommandParser(command).words())
        new_command = ''
        for word in words:
            if word == '[]':
                if posargs:
                    new_command += ' '.join(posargs)
                continue

            new_word = re.sub(pat, self._replace_match, word)
            # two passes; we might have substitutions in the result
            new_word = re.sub(pat, self._replace_match, new_word)
            new_command += new_word

        return shlex.split(new_command.strip())

    def getbool(self, section, name, default=None):
        s = self.getdefault(section, name, default)
        if s is None:
            raise KeyError("no config value [%s] %s found" % (
                section, name))
        if not isinstance(s, bool):
            if s.lower() == "true":
                s = True
            elif s.lower() == "false":
                s = False
            else:
                raise tox.exception.ConfigError(
                    "boolean value %r needs to be 'True' or 'False'")
        return s

    def getdefault(self, section, name, default=None, replace=True):
        try:
            x = self._cfg[section][name]
        except KeyError:
            for fallbacksection in self.fallbacksections:
                try:
                    x = self._cfg[fallbacksection][name]
                except KeyError:
                    pass
                else:
                    break
            else:
                x = default
        if replace and x and hasattr(x, 'replace'):
            self._subststack.append((section, name))
            try:
                x = self._replace(x)
            finally:
                assert self._subststack.pop() == (section, name)
        #print "getdefault", section, name, "returned", repr(x)
        return x

    def _sub(self, match):
        key = match.group(0)[1:-1]
        if key.startswith("env:"):
            envkey = key[4:]
            if envkey not in os.environ:
                raise tox.exception.ConfigError(
                    "substitution %r: %r not found in environment" %
                    (key, envkey))
            return os.environ[envkey]
        val = self._subs.get(key, None)
        if val is None:
            if key.startswith("[") and "]" in key:
                i = key.find("]")
                section, item = key[1:i], key[i+1:]
                if section in self._cfg and item in self._cfg[section]:
                    if (section, item) in self._subststack:
                        raise ValueError('%s already in %s' %(
                                (section, item), self._subststack))
                    x = str(self._cfg[section][item])
                    self._subststack.append((section, item))
                    try:
                        return self._replace(x)
                    finally:
                        self._subststack.pop()

            raise tox.exception.ConfigError(
                "substitution key %r not found" % key)
        if callable(val):
            val = val()
        return str(val)

    def _replace_posargs(self, match):
        return self._do_replace_posargs(lambda: match.group('substitution_value'))

    def _do_replace_posargs(self, value_func):
        posargs = self._subs.get('_posargs', None)

        if posargs:
            return " ".join(posargs)

        value = value_func()
        if value:
            return value

        return ''

    def _replace_env(self, match):
        envkey = match.group('substitution_value')
        if not envkey:
            raise tox.exception.ConfigError(
                'env: requires an environment variable name')

        if not envkey in os.environ:
            raise tox.exception.ConfigError(
                "substitution env:%r: unkown environment variable %r" %
                (envkey, envkey))

        return os.environ[envkey]

    def _replace_substitution(self, match):
        sub_key = match.group('substitution_value')
        if sub_key not in self._subs:
            raise tox.exception.ConfigError(
                "substitution key %r not found" % sub_key)
        return '"%s"' % str(self._subs[sub_key]).replace('"', r'\"')

    def _is_bare_posargs(self, groupdict):
        return groupdict.get('substitution_value', None) == 'posargs' \
               and not groupdict.get('sub_type')

    def _replace_match(self, match):
        g = match.groupdict()

        # special case: posargs. If there is a 'posargs' substitution value
        # and no type, handle it as empty posargs
        if self._is_bare_posargs(g):
            return self._do_replace_posargs(lambda: '')

        handlers = {
            'posargs' : self._replace_posargs,
            'env' : self._replace_env,
            None : self._replace_substitution,
            }
        try:
            sub_type = g['sub_type']
        except KeyError:
            raise tox.exception.ConfigError("Malformed substitution; no substitution type provided")

        try:
            handler = handlers[sub_type]
        except KeyError:
            raise tox.exception.ConfigError("No support for the %s substitution type" % sub_type)

        return handler(match)

    def _replace(self, x, rexpattern = re.compile("\{.+?\}")):
        if '{' in x:
            return rexpattern.sub(self._sub, x)
        return x

    def _parse_command(self, command):
        pass

class CommandParser(object):

    class State(object):
        def __init__(self):
            self.word = ''
            self.depth = 0
            self.yield_words = []

    def __init__(self, command):
        self.command = command

    def words(self):
        ps = CommandParser.State()

        def word_has_ended():
            return ((cur_char in string.whitespace and ps.word and
               ps.word[-1] not in string.whitespace) or
              (cur_char == '{' and ps.depth == 0) or
              (ps.depth == 0 and ps.word and ps.word[-1] == '}') or
              (cur_char not in string.whitespace and ps.word and
               ps.word.strip() == ''))

        def yield_this_word():
            yieldword = ps.word
            ps.word = ''
            if yieldword:
                ps.yield_words.append(yieldword)

        def yield_if_word_ended():
            if word_has_ended():
                yield_this_word()

        def accumulate():
            ps.word += cur_char

        def push_substitution():
            ps.depth += 1

        def pop_substitution():
            ps.depth -= 1

        for cur_char in self.command:
            if cur_char in string.whitespace:
                if ps.depth == 0:
                    yield_if_word_ended()
                accumulate()
            elif cur_char == '{':
                yield_if_word_ended()
                accumulate()
                push_substitution()
            elif cur_char == '}':
                accumulate()
                pop_substitution()
            else:
                yield_if_word_ended()
                accumulate()

        if ps.word.strip():
            yield_this_word()
        return ps.yield_words

def getcontextname():
    if 'HUDSON_URL' in os.environ:
        return 'jenkins'
    return None
