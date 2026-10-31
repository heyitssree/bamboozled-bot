"""Builds the script the SSM document runs: assets/install.sh with run.sh and the unit file embedded."""
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
PARAMS = ("prefix", "env", "region", "port", "logGroup", "bucket", "eniParam")


def assemble() -> str:
    text = (ASSETS / "install.sh").read_text()
    return (text.replace("@@RUN_SH@@", (ASSETS / "run.sh").read_text().rstrip("\n"))
                .replace("@@UNIT@@", (ASSETS / "bamboozled.service").read_text().rstrip("\n")))


def install_commands() -> list[str]:
    """The script written to a file, then run with the document's parameters as arguments."""
    args = " ".join("'{{%s}}'" % p for p in PARAMS)
    return ["cat > /tmp/bamboozled-install.sh <<'BAMBOOZLED_INSTALL_EOF'", *assemble().splitlines(), "BAMBOOZLED_INSTALL_EOF",
            f"bash /tmp/bamboozled-install.sh {args}"]
