"""Report background worker completion and failures to its owner."""


def run_worker(target, args, kwargs, status):
    """Run a target and send a bounded, serializable terminal status."""
    try:
        target(*args, **kwargs)
    except BaseException as error:
        status.send(("error", f"{type(error).__name__}: {str(error)[:1000]}"))
    else:
        status.send(("done", None))
    finally:
        status.close()