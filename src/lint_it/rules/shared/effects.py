from __future__ import annotations

NONDETERMINISTIC = frozenset(
    {
        "datetime.date.today",
        "datetime.datetime.now",
        "datetime.datetime.today",
        "datetime.datetime.utcnow",
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.monotonic_ns",
        "time.perf_counter",
        "time.perf_counter_ns",
        "uuid.uuid1",
        "uuid.uuid4",
        "uuid.uuid6",
        "uuid.uuid7",
        "os.urandom",
    }
)
RANDOM_APIS = frozenset(
    {
        "random",
        "randint",
        "randrange",
        "choice",
        "choices",
        "shuffle",
        "sample",
        "uniform",
        "gauss",
        "getrandbits",
        "randbytes",
        "seed",
        "Random",
        "SystemRandom",
        "normalvariate",
        "triangular",
        "expovariate",
    }
)
SECRETS_APIS = frozenset(
    {"choice", "randbelow", "randbits", "token_bytes", "token_hex", "token_urlsafe", "SystemRandom"}
)
IO_MODULES = frozenset(
    {
        "aiohttp",
        "aiosqlite",
        "asyncpg",
        "boto3",
        "botocore",
        "httpx",
        "playwright",
        "psycopg",
        "psycopg2",
        "redis",
        "requests",
        "socket",
        "subprocess",
    }
)
PATH_EFFECTS = frozenset(
    {
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "exists",
        "is_file",
        "is_dir",
        "is_symlink",
        "stat",
        "lstat",
        "resolve",
        "absolute",
        "iterdir",
        "glob",
        "rglob",
        "walk",
        "mkdir",
        "rmdir",
        "unlink",
        "rename",
        "replace",
        "touch",
        "chmod",
        "owner",
        "group",
        "readlink",
        "symlink_to",
        "hardlink_to",
        "cwd",
        "home",
        "expanduser",
    }
)
LOG_METHODS = frozenset(
    {
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "exception",
        "critical",
        "fatal",
        "log",
        "basicConfig",
        "getLogger",
        "get_logger",
        "addHandler",
        "removeHandler",
        "setLevel",
    }
)
ASYNC_APIS = frozenset(
    {
        "run",
        "create_task",
        "ensure_future",
        "gather",
        "sleep",
        "wait",
        "wait_for",
        "to_thread",
        "TaskGroup",
        "get_event_loop",
        "get_running_loop",
    }
)
AMBIENT = frozenset(
    {
        "os.getenv",
        "os.environ",
        "os.getcwd",
        "os.getcwdb",
        "os.chdir",
        "os.putenv",
        "os.unsetenv",
        "locale.setlocale",
        "locale.getlocale",
        "decimal.getcontext",
        "decimal.setcontext",
        "contextvars.copy_context",
    }
)


def is_nondeterministic(name: str) -> bool:
    module, _, member = name.rpartition(".")
    return (
        name in NONDETERMINISTIC
        or (module == "random" and member in RANDOM_APIS)
        or (module == "secrets" and member in SECRETS_APIS)
    )


def is_ambient(name: str) -> bool:
    return (
        name in AMBIENT
        or name.startswith("os.environ.")
        or name
        in {
            "contextvars.ContextVar.get",
            "contextvars.ContextVar.set",
            "contextvars.ContextVar.reset",
        }
    )


def is_io(name: str) -> bool:
    module, _, member = name.rpartition(".")
    return (
        name.split(".")[0] in IO_MODULES
        or name
        in {
            "builtins.open",
            "builtins.print",
            "builtins.input",
            "io.open",
            "io.FileIO",
            "io.open_code",
        }
        or (
            module in {"pathlib.Path", "pathlib.PosixPath", "pathlib.WindowsPath"}
            and member in PATH_EFFECTS
        )
        or (
            module
            in {
                "logging",
                "logging.Logger",
                "logging.LoggerAdapter",
                "structlog",
                "structlog.BoundLogger",
            }
            and member in LOG_METHODS
        )
        or name.startswith(("urllib.request.", "shutil.", "tempfile."))
        or (
            module == "os"
            and member
            in {
                "open",
                "read",
                "write",
                "stat",
                "listdir",
                "scandir",
                "walk",
                "remove",
                "unlink",
                "mkdir",
                "makedirs",
                "rename",
                "replace",
                "system",
                "popen",
                "fork",
                "kill",
            }
        )
        or (module == "sys" and member in {"exit", "settrace", "setprofile"})
        or name.startswith(("sys.stdout.", "sys.stderr.", "sys.stdin."))
    )


def is_async_effect(name: str) -> bool:
    return (name.startswith("asyncio.") and name.rsplit(".", 1)[-1] in ASYNC_APIS) or name in {
        "threading.Thread",
        "multiprocessing.Process",
        "concurrent.futures.ThreadPoolExecutor",
        "concurrent.futures.ProcessPoolExecutor",
    }


def is_effect(name: str) -> bool:
    return is_nondeterministic(name) or is_ambient(name) or is_io(name) or is_async_effect(name)
