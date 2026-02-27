import os


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_ROOT = os.path.join(WORKSPACE, "code")
DOTENV_PATH = os.path.join(WORKSPACE, ".env")

GENERATED_SOURCE_NAME = "agent_code.s"
GENERATED_ELF_NAME = "agent_code.elf"

MAX_RETRIES = 10
