import copy
import os
import queue
import re
import string
from pathlib import Path

from cryptography.fernet import Fernet
import texteditor
import toml

from .defaults import DEFAULT_SECRETS, DEFAULT_ENCRIPTED_HEADER


__all__ = (
    "MASTER_KEY_FILE",
    "MASTER_KEY_ENV",
    "SecretsNotFound",
    "edit_secrets",
    "generate_key",
    "new_master_key_file",
    "read_secrets",
    "save_secrets",
    "read_master_key",
    "generate_token",
)

Queue = getattr(queue, "SimpleQueue", "Queue")

MASTER_KEY_FILE = "master.key"
MASTER_KEY_ENV = "MASTER_KEY"


def fix_issue_308(self, memo):
    """Temprorary fix until is merged upstream.
    https://github.com/uiri/toml/issues/308
    """
    return self.__class__(self._raw_offset)


toml.tz.TomlTz.__deepcopy__ = fix_issue_308


class SecretsNotFound(Exception):
    def __init__(self, path):
        message = (
            "\nI went looking for `"
            + str(path)
            + "` but it does not exists."
            + "\nYou must specify the path of your secrets file."
        )
        super().__init__(message)


EDIT_INTRO = """You can edit your secrets now, do not forget to save your changes.
Close the editor to proceed."""

EDIT_OUTRO = """Your secrets are safe."""


def edit_secrets(
    path,
    default=None,
    intro=EDIT_INTRO,
    outro=EDIT_OUTRO,
):
    """Edit your encrypted secrets in the default text editor."""
    path = Path(path)
    if not path.exists():
        raise SecretsNotFound(path)
    path.touch()
    content = read_secrets(path, default)
    print(intro)
    new_content = texteditor.open(content, extension=path.suffix)
    save_secrets(path, new_content)
    print(outro)


def generate_key():
    return Fernet.generate_key()


def new_master_key_file(parent_path, master_key_file=MASTER_KEY_FILE):
    master_key = generate_key()
    (Path(parent_path) / master_key_file).write_bytes(master_key)
    return master_key


RX_COMMENT = re.compile(rb"\s*#[^\n]*\n")


def read_secrets(
    secrets_path,
    default="",
    master_key=None,
    master_key_file=MASTER_KEY_FILE,
    master_key_env=MASTER_KEY_ENV,
):
    """Takes a path to an encrypted secrets file and returns its contents.
    decrypted.

    Arguments are:

        secrets_path (str):
            The path to an encripted secrets file.

        master_key (str):
            If not provided, it's assumed that the master_key
            is in the same folder or in an environment variable.

    Returns (str):

        The unencrypted secrets content.

    """
    secrets_path = Path(secrets_path)
    enc_content = RX_COMMENT.sub(b"", secrets_path.read_bytes()).strip()
    if not enc_content:
        return DEFAULT_SECRETS
    master_key = master_key or read_master_key(
        secrets_path.parent,
        master_key_file=master_key_file,
        master_key_env=master_key_env,
    )
    content = Fernet(master_key).decrypt(enc_content)
    return content.decode("utf8")


def save_secrets(
    secrets_path,
    content,
    master_key=None,
    master_key_file=MASTER_KEY_FILE,
    master_key_env=MASTER_KEY_ENV,
):
    """Takes a string, encrypts it using a `master.key` that
    should be in the same folder, saves it at `secrets_path`, and returns the
    unencrypted config.

    Arguments are:

        secrets_path (str):
            The path to an encripted secrets file. It's assumed that the master_key
            is in the same folder or in an environment variable.

        content (str):
            The new content of the secrets file to be encrypted

        master_key (bytes):
            Optional. Use this as master_key, instead of trying to read it from a
            file or an environment variable.

    Returns (dict):

        The unencrypted and parsed-into-a-dict secrets.

    """
    secrets_path = Path(secrets_path)
    master_key = master_key or read_master_key(
        secrets_path.parent,
        master_key_file=master_key_file,
        master_key_env=master_key_env,
    )
    enc_content = Fernet(master_key).encrypt(content.encode("utf8"))
    secrets_path.write_bytes(DEFAULT_ENCRIPTED_HEADER)
    skeleton_header = get_skeleton_header(content)
    with secrets_path.open("ab") as f:
        f.write(skeleton_header.encode("utf8"))
        f.write(b"\n#\n")
        f.write(enc_content)


def read_master_key(
    path,
    error_if_not_found=True,
    master_key_file=MASTER_KEY_FILE,
    master_key_env=MASTER_KEY_ENV,
):
    path = Path(path)
    master_key = os.getenv(master_key_env, "").strip().encode("utf8")
    if not master_key:
        master_key_path = path / master_key_file
        if not master_key_path.is_file():
            master_key_path = path.parent / master_key_file
        if master_key_path.is_file():
            master_key = master_key_path.read_bytes().strip()

    if error_if_not_found and not master_key:
        raise IOError(
            f"Key not found. Either put a `{master_key_file}` beside your"
            " secrets file, in the parent folder, or set and environment"
            f" variable `{master_key_env}` with the master_key value"
            " (the environment variable takes precendence over the file)."
        )
    return master_key


CHARS = string.ascii_letters + string.digits + "&*"
CHARS_LEN = 64
SECRET_LENGTH = 64


def generate_token(length=SECRET_LENGTH):
    return "".join([CHARS[ord(os.urandom(1)) % CHARS_LEN] for i in range(length)])


def get_skeleton(config, maxdepth=2, empty="..."):
    """Takes a dict and return another with all the non-dict values
    or those deeper than `maxdepth` replaced by `empty`.
    """
    dicts = Queue()
    skeleton = copy.deepcopy(config)
    dicts.put((0, skeleton))

    while dicts.qsize() > 0:
        level, subdict = dicts.get()
        for key, value in subdict.items():
            if level < maxdepth and isinstance(value, dict):
                dicts.put((level + 1, value))
                continue
            subdict[key] = empty

    return skeleton


def get_skeleton_header(content):
    try:
        config = toml.loads(content)
    except toml.TomlDecodeError:
        print(
            "-- WARNING: The encrypted config has syntax errors and"
            " is not a valid TOML file."
        )
        return ""

    sk = get_skeleton(config)
    text = toml.dumps(sk).strip()
    return "#  " + "\n#  ".join(text.split("\n"))
