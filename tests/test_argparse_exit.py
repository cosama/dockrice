import pytest
from dockrice.argparse import ArgumentParser, DockerizeDoneExit, DockerProcessError


def test_argparse_exit_classes():
    assert issubclass(DockerizeDoneExit, SystemExit)
    assert issubclass(DockerProcessError, SystemExit)

    success_exit = DockerizeDoneExit(0)
    assert success_exit.code == 0

    err_exit = DockerProcessError(1, cmd=["python", "test.py"])
    assert err_exit.code == 1
    assert err_exit.returncode == 1
    assert "code 1" in str(err_exit)
    assert "test.py" in str(err_exit)


def test_parse_known_args_success(monkeypatch):
    parser = ArgumentParser(script_name="dummy.py", image="dummy:latest")
    monkeypatch.setattr(parser._docker_action_factory, "run_docker", lambda *a, **kw: 0)

    with pytest.raises(DockerizeDoneExit) as excinfo:
        parser.parse_known_args([])
    assert excinfo.value.code == 0
    assert isinstance(excinfo.value, SystemExit)


def test_parse_known_args_failure(monkeypatch):
    parser = ArgumentParser(script_name="dummy.py", image="dummy:latest")
    monkeypatch.setattr(parser._docker_action_factory, "run_docker", lambda *a, **kw: 42)

    with pytest.raises(DockerProcessError) as excinfo:
        parser.parse_known_args([])
    assert excinfo.value.code == 42
    assert excinfo.value.returncode == 42
    assert isinstance(excinfo.value, SystemExit)
    assert not isinstance(excinfo.value, DockerizeDoneExit)


def test_clean_chaining_pattern(monkeypatch):
    parser_success = ArgumentParser(script_name="dummy.py", image="dummy:latest")
    monkeypatch.setattr(parser_success._docker_action_factory, "run_docker", lambda *a, **kw: 0)

    # Success only catches DockerizeDoneExit
    try:
        parser_success.parse_known_args([])
    except DockerizeDoneExit:
        pass

    # Failure raises DockerProcessError, NOT caught by DockerizeDoneExit
    parser_fail = ArgumentParser(script_name="dummy.py", image="dummy:latest")
    monkeypatch.setattr(parser_fail._docker_action_factory, "run_docker", lambda *a, **kw: 1)

    with pytest.raises(DockerProcessError):
        try:
            parser_fail.parse_known_args([])
        except DockerizeDoneExit:
            pass


def test_backwards_compatible_systemexit(monkeypatch):
    parser_success = ArgumentParser(script_name="dummy.py", image="dummy:latest")
    monkeypatch.setattr(parser_success._docker_action_factory, "run_docker", lambda *a, **kw: 0)

    try:
        parser_success.parse_known_args([])
    except SystemExit as e:
        if e.code:
            raise e

    parser_fail = ArgumentParser(script_name="dummy.py", image="dummy:latest")
    monkeypatch.setattr(parser_fail._docker_action_factory, "run_docker", lambda *a, **kw: 1)

    with pytest.raises(SystemExit) as excinfo:
        try:
            parser_fail.parse_known_args([])
        except SystemExit as e:
            if e.code:
                raise e
    assert excinfo.value.code == 1
