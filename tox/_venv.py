
import sys, os
import py
import tox

class CreationConfig:
    def __init__(self, md5, python, version, distribute, sitepackages, deps):
        self.md5 = md5
        self.python = python
        self.version = version
        self.distribute = distribute
        self.sitepackages = sitepackages
        self.deps = deps

    def writeconfig(self, path):
        lines = ["%s %s" % (self.md5, self.python)]
        lines.append("%s %d %d" % (self.version, self.distribute,
                        self.sitepackages))
        for dep in self.deps:
            lines.append("%s %s" % dep)
        path.write("\n".join(lines))

    @classmethod
    def readconfig(cls, path):
        try:
            lines = path.readlines(cr=0)
            value = lines.pop(0).split(None, 1)
            md5, python = value
            version, distribute, sitepackages = lines.pop(0).split(None, 2)
            distribute = bool(int(distribute))
            sitepackages = bool(int(sitepackages))
            deps = []
            for line in lines:
                md5, depstring = line.split(None, 1)
                deps.append((md5, depstring))
            return CreationConfig(md5, python, version,
                        distribute, sitepackages, deps)
        except KeyboardInterrupt:
            raise
        except:
            return None

    def matches(self, other):
        return (other and self.md5 == other.md5
           and self.python == other.python
           and self.version == other.version
           and self.distribute == other.distribute
           and self.sitepackages == other.sitepackages
           and self.deps == other.deps)

class VirtualEnv(object):
    def __init__(self, envconfig=None, session=None):
        self.envconfig = envconfig
        self.session = session
        self.path = envconfig.envdir
        self.path_config = self.path.join(".tox-config1")

    def __repr__(self):
        return "<VirtualEnv at %r>" %(self.path)

    def getcommandpath(self, name=None):
        if name is None:
            return self.envconfig.envpython
        if os.path.isabs(name):
            return name
        p = py.path.local.sysfind(name)
        if p is None:
            raise tox.exception.InvocationError("could not find executable %r"
                % (name,))
        if p.relto(self.envconfig.envdir):
            return p
        return str(p) # will not be rewritten for reporting

    def _ispython3(self):
        return "python3" in str(self.envconfig.basepython)

    def update(self):
        """ return status string for updating actual venv to match configuration.
            if status string is empty, all is ok.
        """
        report = self.session.report
        name = self.envconfig.envname
        rconfig = CreationConfig.readconfig(self.path_config)
        if rconfig and rconfig.matches(self._getliveconfig()):
            report.action("reusing existing matching virtualenv %s" %
                (self.envconfig.envname,))
            return
        if rconfig is None:
            report.action("creating virtualenv %s" % name)
        else:
            report.action("recreating virtualenv %s "
                "(configchange/incomplete install detected)" % name)
        try:
            self.create()
        except tox.exception.UnsupportedInterpreter:
            return sys.exc_info()[1]
        except tox.exception.InterpreterNotFound:
            return sys.exc_info()[1]
        try:
            self.install_deps()
        except tox.exception.InvocationError:
            v = sys.exc_info()[1]
            return "could not install deps %r" %(
                    ",".join(self.envconfig.deps))

    def _getliveconfig(self):
        python = self.getconfigexecutable()
        md5 = getdigest(python)
        version = tox.__version__
        distribute = self.envconfig.distribute
        sitepackages = self.envconfig.sitepackages
        deps = []
        for raw_dep in self._getresolvedeps():
            md5 = getdigest(raw_dep)
            deps.append((md5, raw_dep))
        return CreationConfig(md5, python, version,
                        distribute, sitepackages, deps)

    def _getresolvedeps(self):
        return [self.session._resolve_pkg(dep) for dep in self.envconfig.deps]

    def getconfigexecutable(self):
        python = self.envconfig.basepython
        if not python:
            python = sys.executable
        x = find_executable(str(python))
        if x:
            x = x.realpath()
        return x

    def getsupportedinterpreter(self):
        if sys.platform == "win32" and self._ispython3():
            raise tox.exception.UnsupportedInterpreter(
                "python3/virtualenv3 is buggy on windows")
        if sys.platform == "win32" and self.envconfig.basepython and \
                "jython" in self.envconfig.basepython:
            raise tox.exception.UnsupportedInterpreter(
                "Jython/Windows does not support installing scripts")
        config_executable = self.getconfigexecutable()
        if not config_executable:
            raise tox.exception.InterpreterNotFound(self.envconfig.basepython)
        return config_executable

    def create(self):
        #if self.getcommandpath("activate").dirpath().check():
        #    return
        config_interpreter = self.getsupportedinterpreter()
        args = ['virtualenv' + (self._ispython3() and "5" or "")]
        if not self._ispython3() and self.envconfig.distribute:
            args.append('--distribute')
        if not self.envconfig.sitepackages:
            args.append('--no-site-packages')
        if sys.platform == "win32":
            f, path, _ = py.std.imp.find_module("virtualenv")
            f.close()
            args[:1] = [str(config_interpreter), str(path)]
        else:
            args.extend(["-p", str(config_interpreter)])
        self.session.make_emptydir(self.path)
        basepath = self.path.dirpath()
        basepath.ensure(dir=1)
        old = py.path.local()
        try:
            basepath.chdir()
            args.append(self.path.basename)
            self._pcall(args, venv=False)
            #if self._ispython3():
            #    self.easy_install(["-U", "distribute"])
        finally:
            old.chdir()
        self._getliveconfig().writeconfig(self.path_config)

    def install_sdist(self, sdistpath):
        self._install([sdistpath])

    def install_deps(self):
        deps = self._getresolvedeps()
        self.session.report.action("installing dependencies %s" %(deps))
        self._install(deps)

    def easy_install(self, args):
        argv = ["easy_install"] + args
        self._pcall(argv, cwd=self.envconfig.envlogdir)

    def pip_install(self, args):
        argv = ["pip", "install"] + args
        if self.envconfig.downloadcache:
            self.envconfig.downloadcache.ensure(dir=1)
            argv.append("--download-cache=%s" %
                self.envconfig.downloadcache)
        self._pcall(argv, cwd=self.envconfig.envlogdir)

    def _install(self, args):
        if not args:
            return
        if self._ispython3():
            self.easy_install(args)
        else:
            self.pip_install(args)

    def test(self):
        self.session.make_emptydir(self.envconfig.envtmpdir)
        cwd = self.envconfig.changedir
        for argv in self.envconfig.commands:
            try:
                self._pcall(argv, log=-1, cwd=cwd)
            except tox.exception.InvocationError:
                return True

    def _pcall(self, args, venv=True, log=None, cwd=None):
        try:
            del os.environ['PYTHONDONTWRITEBYTECODE']
        except KeyError:
            pass
        old = self.patchPATH()
        try:
            if venv:
                args = [self.getcommandpath(args[0])] + args[1:]
            if log is None:
                log = self.path.ensure("log", dir=1)
            return self.session.pcall(args, log=log, cwd=cwd)
        finally:
            os.environ['PATH'] = old

    def patchPATH(self):
        oldPATH = os.environ['PATH']
        bindir = str(self.envconfig.envbindir)
        os.environ['PATH'] = os.pathsep.join([bindir, oldPATH])
        return oldPATH

def getdigest(path):
    path = py.path.local(path)
    if not path.check():
        return "0" * 32
    return path.computehash()

if sys.platform != "win32":
    def find_executable(name):
        return py.path.local.sysfind(name)

else:
    win32map = {
            'python': sys.executable,
            'python2.4': "c:\python24\python.exe",
            'python2.5': "c:\python25\python.exe",
            'python2.6': "c:\python26\python.exe",
            'python2.7': "c:\python27\python.exe",
            'python3.1': "c:\python31\python.exe",
            'python3.2': "c:\python32\python.exe",
            'jython': "c:\jython2.5.1\jython.bat",
    }
    def find_executable(name):
        p = py.path.local(name)
        if p.check(file=1):
            return p
        actual = win32map.get(name, None)
        if actual:
            actual = py.path.local(actual)
            if actual.check():
                return actual


