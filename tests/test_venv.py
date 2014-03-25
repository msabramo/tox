import py
import tox
import pytest
import os, sys
import tox._config
from tox._venv import *

#def test_global_virtualenv(capfd):
#    v = VirtualEnv()
#    l = v.list()
#    assert l
#    out, err = capfd.readouterr()
#    assert not out
#    assert not err
#
def test_getdigest(tmpdir):
    assert getdigest(tmpdir) == "0"*32

def test_getsupportedinterpreter(monkeypatch, newconfig, mocksession):
    config = newconfig([], """
        [testenv:python]
        basepython=%s
    """ % sys.executable)
    venv = VirtualEnv(config.envconfigs['python'], session=mocksession)
    interp = venv.getsupportedinterpreter()
    # realpath needed for debian symlinks
    assert py.path.local(interp).realpath() \
      == py.path.local(sys.executable).realpath()
    monkeypatch.setattr(sys, 'platform', "win32")
    monkeypatch.setattr(venv.envconfig, 'basepython', 'jython')
    py.test.raises(tox.exception.UnsupportedInterpreter,
                   venv.getsupportedinterpreter)
    monkeypatch.undo()
    monkeypatch.setattr(venv.envconfig, 'basepython', 'notexistingpython')
    py.test.raises(tox.exception.InterpreterNotFound,
                   venv.getsupportedinterpreter)


def test_create(monkeypatch, mocksession, newconfig):
    config = newconfig([], """
        [testenv:py123]
    """)
    envconfig = config.envconfigs['py123']
    venv = VirtualEnv(envconfig, session=mocksession)
    assert venv.path == envconfig.envdir
    assert not venv.path.check()
    venv.create()
    l = mocksession._pcalls
    assert len(l) >= 1
    args = l[0].args
    assert "virtualenv" in str(args[1])
    if sys.platform != "win32":
        # realpath is needed for stuff like the debian symlinks
        assert py.path.local(sys.executable).realpath() \
          == py.path.local(args[0]).realpath()
        #assert Envconfig.toxworkdir in args
        assert venv.getcommandpath("easy_install", cwd=py.path.local())
    interp = venv._getliveconfig().python
    assert interp == venv.envconfig._basepython_info.executable
    assert venv.path_config.check(exists=False)

@pytest.mark.skipif("sys.platform == 'win32'")
def test_commandpath_venv_precendence(tmpdir, monkeypatch,
                                      mocksession, newconfig):
    config = newconfig([], """
        [testenv:py123]
    """)
    envconfig = config.envconfigs['py123']
    venv = VirtualEnv(envconfig, session=mocksession)
    tmpdir.ensure("easy_install")
    monkeypatch.setenv("PATH", str(tmpdir), prepend=os.pathsep)
    envconfig.envbindir.ensure("easy_install")
    p = venv.getcommandpath("easy_install")
    assert py.path.local(p).relto(envconfig.envbindir), p

def test_create_distribute(monkeypatch, mocksession, newconfig):
    config = newconfig([], """
        [testenv:py123]
        distribute=False
    """)
    envconfig = config.envconfigs['py123']
    venv = VirtualEnv(envconfig, session=mocksession)
    assert venv.path == envconfig.envdir
    assert not venv.path.check()
    venv.create()
    l = mocksession._pcalls
    assert len(l) >= 1
    args = l[0].args
    assert "--distribute" not in map(str, args)
    assert "--setuptools" in map(str, args)

def test_create_sitepackages(monkeypatch, mocksession, newconfig):
    config = newconfig([], """
        [testenv:site]
        sitepackages=True

        [testenv:nosite]
        sitepackages=False
    """)
    envconfig = config.envconfigs['site']
    venv = VirtualEnv(envconfig, session=mocksession)
    venv.create()
    l = mocksession._pcalls
    assert len(l) >= 1
    args = l[0].args
    assert "--system-site-packages" in map(str, args)
    mocksession._clearmocks()

    envconfig = config.envconfigs['nosite']
    venv = VirtualEnv(envconfig, session=mocksession)
    venv.create()
    l = mocksession._pcalls
    assert len(l) >= 1
    args = l[0].args
    assert "--system-site-packages" not in map(str, args)
    assert "--no-site-packages" not in map(str, args)

def test_install_deps_wildcard(newmocksession):
    mocksession = newmocksession([], """
        [tox]
        distshare = {toxworkdir}/distshare
        [testenv:py123]
        deps=
            {distshare}/dep1-*
    """)
    venv = mocksession.getenv("py123")
    venv.create()
    l = mocksession._pcalls
    assert len(l) == 1
    distshare = venv.session.config.distshare
    distshare.ensure("dep1-1.0.zip")
    distshare.ensure("dep1-1.1.zip")

    venv.install_deps()
    assert len(l) == 2
    args = l[-1].args
    assert l[-1].cwd == venv.envconfig.config.toxinidir
    assert "pip" in str(args[0])
    assert args[1] == "install"
    #arg = "--download-cache=" + str(venv.envconfig.downloadcache)
    #assert arg in args[2:]
    args = [arg for arg in args if str(arg).endswith("dep1-1.1.zip")]
    assert len(args) == 1


@pytest.mark.parametrize("envdc", [True, False])
def test_install_downloadcache(newmocksession, monkeypatch, tmpdir, envdc):
    if envdc:
        monkeypatch.setenv("PIP_DOWNLOAD_CACHE", tmpdir)
    else:
        monkeypatch.delenv("PIP_DOWNLOAD_CACHE", raising=False)
    mocksession = newmocksession([], """
        [testenv:py123]
        distribute=True
        deps=
            dep1
            dep2
    """)
    venv = mocksession.getenv("py123")
    venv.create()
    l = mocksession._pcalls
    assert len(l) == 1

    venv.install_deps()
    assert len(l) == 2
    args = l[-1].args
    assert l[-1].cwd == venv.envconfig.config.toxinidir
    assert "pip" in str(args[0])
    assert args[1] == "install"
    assert "dep1" in args
    assert "dep2" in args
    deps = list(filter(None, [x[1] for x in venv._getliveconfig().deps]))
    assert deps == ['dep1', 'dep2']

def test_install_deps_indexserver(newmocksession):
    mocksession = newmocksession([], """
        [tox]
        indexserver =
            abc = ABC
            abc2 = ABC
        [testenv:py123]
        deps=
            dep1
            :abc:dep2
            :abc2:dep3
    """)
    venv = mocksession.getenv('py123')
    venv.create()
    l = mocksession._pcalls
    assert len(l) == 1
    l[:] = []

    venv.install_deps()
    # two different index servers, two calls
    assert len(l) == 3
    args = " ".join(l[0].args)
    assert "-i " not in args
    assert "dep1" in args

    args = " ".join(l[1].args)
    assert "-i ABC" in args
    assert "dep2" in args
    args = " ".join(l[2].args)
    assert "-i ABC" in args
    assert "dep3" in args

def test_installpkg_indexserver(newmocksession, tmpdir):
    mocksession = newmocksession([], """
        [tox]
        indexserver =
            default = ABC
    """)
    venv = mocksession.getenv('python')
    l = mocksession._pcalls
    p = tmpdir.ensure("distfile.tar.gz")
    mocksession.installpkg(venv, p)
    # two different index servers, two calls
    assert len(l) == 1
    args = " ".join(l[0].args)
    assert "-i ABC" in args

def test_install_recreate(newmocksession, tmpdir):
    pkg = tmpdir.ensure("package.tar.gz")
    mocksession = newmocksession(['--recreate'], """
        [testenv]
        deps=xyz
    """)
    venv = mocksession.getenv('python')
    venv.update()
    mocksession.installpkg(venv, pkg)
    mocksession.report.expect("verbosity0", "*create*")
    venv.update()
    mocksession.report.expect("verbosity0", "*recreate*")

def test_test_hashseed_is_in_output(newmocksession):
    original_make_hashseed = tox._config.make_hashseed
    tox._config.make_hashseed = lambda: '123456789'
    try:
        mocksession = newmocksession([], '''
            [testenv]
        ''')
    finally:
        tox._config.make_hashseed = original_make_hashseed
    venv = mocksession.getenv('python')
    venv.update()
    venv.test()
    mocksession.report.expect("verbosity0", "python runtests: PYTHONHASHSEED='123456789'")

def test_test_runtests_action_command_is_in_output(newmocksession):
    mocksession = newmocksession([], '''
        [testenv]
        commands = echo foo bar
    ''')
    venv = mocksession.getenv('python')
    venv.update()
    venv.test()
    mocksession.report.expect("verbosity0", "*runtests*commands?0? | echo foo bar")

def test_install_error(newmocksession, monkeypatch):
    mocksession = newmocksession(['--recreate'], """
        [testenv]
        deps=xyz
        commands=
            qwelkqw
    """)
    venv = mocksession.getenv('python')
    venv.test()
    mocksession.report.expect("error", "*not find*qwelkqw*")
    assert venv.status == "commands failed"

def test_install_command_not_installed(newmocksession, monkeypatch):
    mocksession = newmocksession(['--recreate'], """
        [testenv]
        commands=
            py.test
    """)
    venv = mocksession.getenv('python')
    venv.test()
    mocksession.report.expect("warning", "*test command found but not*")
    assert venv.status == "commands failed"

def test_install_command_whitelisted(newmocksession, monkeypatch):
    mocksession = newmocksession(['--recreate'], """
        [testenv]
        whitelist_externals = py.test
                              xy*
        commands=
            py.test
            xyz
    """)
    venv = mocksession.getenv('python')
    venv.test()
    mocksession.report.expect("warning", "*test command found but not*",
                              invert=True)
    assert venv.status == "commands failed"

@pytest.mark.skipif("not sys.platform.startswith('linux')")
def test_install_command_not_installed(newmocksession):
    mocksession = newmocksession(['--recreate'], """
        [testenv]
        commands=
            bash
    """)
    venv = mocksession.getenv('python')
    venv.test()
    mocksession.report.expect("warning", "*test command found but not*")


def test_install_python3(tmpdir, newmocksession):
    if not py.path.local.sysfind('python3.3'):
        pytest.skip("needs python3.3")
    mocksession = newmocksession([], """
        [testenv:py123]
        basepython=python3.3
        deps=
            dep1
            dep2
    """)
    venv = mocksession.getenv('py123')
    venv.create()
    l = mocksession._pcalls
    assert len(l) == 1
    args = l[0].args
    assert str(args[1]).endswith('virtualenv')
    l[:] = []
    action = mocksession.newaction(venv, "hello")
    venv._install(["hello"], action=action)
    assert len(l) == 1
    args = l[0].args
    assert 'pip' in str(args[0])
    for x in args:
        assert "--download-cache" not in args, args

class TestCreationConfig:

    def test_basic(self, newconfig, mocksession, tmpdir):
        config = newconfig([], "")
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        cconfig = venv._getliveconfig()
        assert cconfig.matches(cconfig)
        path = tmpdir.join("configdump")
        cconfig.writeconfig(path)
        newconfig = CreationConfig.readconfig(path)
        assert newconfig.matches(cconfig)
        assert cconfig.matches(newconfig)

    def test_matchingdependencies(self, newconfig, mocksession):
        config = newconfig([], """
            [testenv]
            deps=abc
        """)
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        cconfig = venv._getliveconfig()
        config = newconfig([], """
            [testenv]
            deps=xyz
        """)
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        otherconfig = venv._getliveconfig()
        assert not cconfig.matches(otherconfig)

    def test_matchingdependencies_file(self, newconfig, mocksession):
        config = newconfig([], """
            [tox]
            distshare={toxworkdir}/distshare
            [testenv]
            deps=abc
                 {distshare}/xyz.zip
        """)
        xyz = config.distshare.join("xyz.zip")
        xyz.ensure()
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        cconfig = venv._getliveconfig()
        assert cconfig.matches(cconfig)
        xyz.write("hello")
        newconfig = venv._getliveconfig()
        assert not cconfig.matches(newconfig)

    def test_matchingdependencies_latest(self, newconfig, mocksession):
        config = newconfig([], """
            [tox]
            distshare={toxworkdir}/distshare
            [testenv]
            deps={distshare}/xyz-*
        """)
        xyz = config.distshare.ensure("xyz-1.2.0.zip")
        xyz2 = config.distshare.ensure("xyz-1.2.1.zip")
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        cconfig = venv._getliveconfig()
        md5, path = cconfig.deps[0]
        assert path == xyz2
        assert md5 == path.computehash()

    def test_python_recreation(self, tmpdir, newconfig, mocksession):
        pkg = tmpdir.ensure("package.tar.gz")
        config = newconfig([], "")
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        cconfig = venv._getliveconfig()
        venv.update()
        assert not venv.path_config.check()
        mocksession.installpkg(venv, pkg)
        assert venv.path_config.check()
        assert mocksession._pcalls
        args1 = map(str, mocksession._pcalls[0].args)
        assert 'virtualenv' in " ".join(args1)
        mocksession.report.expect("*", "*create*")
        # modify config and check that recreation happens
        mocksession._clearmocks()
        venv.update()
        mocksession.report.expect("*", "*reusing*")
        mocksession._clearmocks()
        cconfig.python = py.path.local("balla")
        cconfig.writeconfig(venv.path_config)
        venv.update()
        mocksession.report.expect("verbosity0", "*recreate*")

    def test_dep_recreation(self, newconfig, mocksession):
        config = newconfig([], "")
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        venv.update()
        cconfig = venv._getliveconfig()
        cconfig.deps[:] = [("1"*32, "xyz.zip")]
        cconfig.writeconfig(venv.path_config)
        mocksession._clearmocks()
        venv.update()
        mocksession.report.expect("*", "*recreate*")

    def test_distribute_recreation(self, newconfig, mocksession):
        config = newconfig([], "")
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        venv.update()
        cconfig = venv._getliveconfig()
        cconfig.distribute = True
        cconfig.writeconfig(venv.path_config)
        mocksession._clearmocks()
        venv.update()
        mocksession.report.expect("verbosity0", "*recreate*")

    def test_develop_recreation(self, newconfig, mocksession):
        config = newconfig([], "")
        envconfig = config.envconfigs['python']
        venv = VirtualEnv(envconfig, session=mocksession)
        venv.update()
        cconfig = venv._getliveconfig()
        cconfig.develop = True
        cconfig.writeconfig(venv.path_config)
        mocksession._clearmocks()
        venv.update()
        mocksession.report.expect("verbosity0", "*recreate*")

class TestVenvTest:

    def test_patchPATH(self, newmocksession, monkeypatch):
        monkeypatch.setenv("PIP_RESPECT_VIRTUALENV", "1")
        mocksession = newmocksession([], """
            [testenv:python]
            commands=abc
        """)
        venv = mocksession.getenv("python")
        envconfig = venv.envconfig
        monkeypatch.setenv("PATH", "xyz")
        oldpath = venv.patchPATH()
        assert oldpath == "xyz"
        res = os.environ['PATH']
        assert res == "%s%sxyz" % (envconfig.envbindir, os.pathsep)
        p = "xyz"+os.pathsep+str(envconfig.envbindir)
        monkeypatch.setenv("PATH", p)
        venv.patchPATH()
        res = os.environ['PATH']
        assert res == "%s%s%s" %(envconfig.envbindir, os.pathsep, p)

        assert envconfig.commands
        monkeypatch.setattr(venv, '_pcall', lambda *args, **kwargs: 0/0)
        py.test.raises(ZeroDivisionError, "venv._install(list('123'))")
        py.test.raises(ZeroDivisionError, "venv.test()")
        py.test.raises(ZeroDivisionError, "venv.run_install_command(['qwe'])")
        py.test.raises(ZeroDivisionError, "venv._pcall([1,2,3])")
        monkeypatch.setenv("PIP_RESPECT_VIRTUALENV", "1")
        monkeypatch.setenv("PIP_REQUIRE_VIRTUALENV", "1")
        py.test.raises(ZeroDivisionError, "venv.run_install_command(['qwe'])")
        assert 'PIP_RESPECT_VIRTUALENV' not in os.environ
        assert 'PIP_REQUIRE_VIRTUALENV' not in os.environ

def test_setenv_added_to_pcall(tmpdir, mocksession, newconfig):
    pkg = tmpdir.ensure("package.tar.gz")
    config = newconfig([], """
        [testenv:python]
        commands=python -V
        setenv =
            ENV_VAR = value
    """)
    mocksession._clearmocks()

    venv = VirtualEnv(config.envconfigs['python'], session=mocksession)
    # import pdb; pdb.set_trace()
    mocksession.installpkg(venv, pkg)
    venv.test()

    l = mocksession._pcalls
    assert len(l) == 2
    for x in l:
        args = x.args
        env = x.env
        assert env is not None
        assert 'ENV_VAR' in env
        assert env['ENV_VAR'] == 'value'

    for e in os.environ:
        assert e in env

def test_installpkg_no_upgrade(tmpdir, newmocksession):
    pkg = tmpdir.ensure("package.tar.gz")
    mocksession = newmocksession([], "")
    venv = mocksession.getenv('python')
    venv.just_created = True
    venv.envconfig.envdir.ensure(dir=1)
    mocksession.installpkg(venv, pkg)
    l = mocksession._pcalls
    assert len(l) == 1
    assert '-U' not in l[0].args

def test_installpkg_upgrade(newmocksession, tmpdir):
    pkg = tmpdir.ensure("package.tar.gz")
    mocksession = newmocksession([], "")
    venv = mocksession.getenv('python')
    assert not hasattr(venv, 'just_created')
    mocksession.installpkg(venv, pkg)
    l = mocksession._pcalls
    assert len(l) == 1
    index = l[0].args.index(str(pkg))
    assert index >= 0
    assert '-U' in l[0].args[:index]
    assert '--no-deps' in l[0].args[:index]

def test_run_install_command(newmocksession):
    mocksession = newmocksession([], "")
    venv = mocksession.getenv('python')
    venv.just_created = True
    venv.envconfig.envdir.ensure(dir=1)
    action = mocksession.newaction(venv, "hello")
    venv.run_install_command(packages=["whatever"], action=action)
    l = mocksession._pcalls
    assert len(l) == 1
    assert 'pip' in l[0].args[0]
    assert 'install' in l[0].args
    env = l[0].env
    assert env is not None
    assert 'PYTHONIOENCODING' in env
    assert env['PYTHONIOENCODING'] == 'utf_8'

def test_run_custom_install_command(newmocksession):
    mocksession = newmocksession([], """
        [testenv]
        install_command=easy_install {opts} {packages}
    """)
    venv = mocksession.getenv('python')
    venv.just_created = True
    venv.envconfig.envdir.ensure(dir=1)
    action = mocksession.newaction(venv, "hello")
    venv.run_install_command(packages=["whatever"], action=action)
    l = mocksession._pcalls
    assert len(l) == 1
    assert 'easy_install' in l[0].args[0]
    assert l[0].args[1:] == ['whatever']

def test_command_relative_issue26(newmocksession, tmpdir, monkeypatch):
    mocksession = newmocksession([], """
        [testenv]
    """)
    x = tmpdir.ensure("x")
    venv = mocksession.getenv("python")
    x2 = venv.getcommandpath("./x", cwd=tmpdir)
    assert x == x2
    mocksession.report.not_expect("warning", "*test command found but not*")
    x3 = venv.getcommandpath("/bin/bash", cwd=tmpdir)
    assert x3 == "/bin/bash"
    mocksession.report.not_expect("warning", "*test command found but not*")
    monkeypatch.setenv("PATH", str(tmpdir))
    x4 = venv.getcommandpath("x", cwd=tmpdir)
    mocksession.report.expect("warning", "*test command found but not*")

def test_sethome_only_on_option(newmocksession, monkeypatch):
    mocksession = newmocksession([], "")
    venv = mocksession.getenv('python')
    action = mocksession.newaction(venv, "qwe", [])
    monkeypatch.setattr(tox._venv, "hack_home_env", None)
    venv._install(["x"], action=action)

def test_sethome_works_on_option(newmocksession, monkeypatch):
    mocksession = newmocksession(["--set-home", "-i ALL=http://qwe"], "")
    venv = mocksession.getenv('python')
    action = mocksession.newaction(venv, "qwe", [])
    venv._install(["x"], action=action)
    _, mocked = mocksession.report.getnext("logpopen")
    p = mocked.env["HOME"]
    pydist = py.path.local(p).join(".pydistutils.cfg")
    assert "http://qwe" in pydist.read()


def test_hack_home_env(tmpdir):
    from tox._venv import hack_home_env
    env = hack_home_env(tmpdir, "http://index")
    assert env["HOME"] == str(tmpdir)
    assert env["PIP_INDEX_URL"] == "http://index"
    assert "index_url = http://index" in \
           tmpdir.join(".pydistutils.cfg").read()
    tmpdir.remove()
    env = hack_home_env(tmpdir, None)
    assert env["HOME"] == str(tmpdir)
    assert not tmpdir.join(".pydistutils.cfg").check()
    assert "PIP_INDEX_URL" not in env

def test_hack_home_env_passthrough(tmpdir, monkeypatch):
    from tox._venv import hack_home_env
    env = hack_home_env(tmpdir, "http://index")
    monkeypatch.setattr(os, "environ", env)

    tmpdir = tmpdir.mkdir("tmpdir2")
    env2 = hack_home_env(tmpdir)
    assert env2["HOME"] == str(tmpdir)
    assert env2["PIP_INDEX_URL"] == "http://index"
    assert "index_url = http://index" in \
           tmpdir.join(".pydistutils.cfg").read()
