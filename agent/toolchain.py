import os
import subprocess
from dataclasses import dataclass


DEFAULT_ARMCLANG_BIN = "/opt/arm/developmentstudio-2025.0-1/sw/ARMCompiler6.24/bin/armclang"
DEFAULT_ARMLINK_BIN = "/opt/arm/developmentstudio-2025.0-1/sw/ARMCompiler6.24/bin/armlink"
DEFAULT_FVP_BIN = "/opt/arm/developmentstudio-2025.0-1/bin/FVP_BaseR_Cortex-R52"


@dataclass(frozen=True)
class ToolchainBinaries:
    armclang_bin: str
    armlink_bin: str
    fvp_bin: str


def load_toolchain_binaries_from_env() -> ToolchainBinaries:
    return ToolchainBinaries(
        armclang_bin=os.environ.get("ARMCLANG_BIN", DEFAULT_ARMCLANG_BIN),
        armlink_bin=os.environ.get("ARMLINK_BIN", DEFAULT_ARMLINK_BIN),
        fvp_bin=os.environ.get("FVP_BIN", DEFAULT_FVP_BIN),
    )


def get_target_details(toolchain: str) -> tuple[str, str]:
    if toolchain == "gcc":
        return "0x101F1000", "QEMU versatilepb"
    return "0x9C090000", "FVP Cortex-R52"


def compile_code(
    source_file: str,
    elf_file: str,
    toolchain: str,
    code_dir: str,
    workspace: str,
    binaries: ToolchainBinaries,
) -> tuple[bool, str]:
    """
    Compile the generated code.
    Returns (success: bool, error_message: str)
    """
    print(f"\n[Compiler] Compiling {source_file} using {toolchain}...")
    obj_file = os.path.join(code_dir, "agent_code.o")

    if toolchain == "ds5":
        compile_cmd = [
            binaries.armclang_bin,
            "--target=arm-arm-none-eabi",
            "-mcpu=cortex-r52",
            "-O0",
            "-c",
            source_file,
            "-o",
            obj_file,
        ]
        link_cmd = [
            binaries.armlink_bin,
            "--ro-base=0x00000000",
            "--entry=_start",
            obj_file,
            "-o",
            elf_file,
        ]

        try:
            subprocess.run(compile_cmd, capture_output=True, text=True, check=True)
            subprocess.run(link_cmd, capture_output=True, text=True, check=True)
            print("[Compiler] Success!")
            return True, ""
        except subprocess.CalledProcessError as e:
            print("[Compiler] Failed!")
            return False, e.stderr

    cmd = [
        "arm-none-eabi-gcc",
        "-O0",
        "-nostdlib",
        "-T",
        os.path.join(workspace, "link.ld"),
        source_file,
        "-o",
        elf_file,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("[Compiler] Success!")
        return True, ""
    except subprocess.CalledProcessError as e:
        print("[Compiler] Failed!")
        return False, e.stderr


def run_in_simulator(
    elf_file: str,
    toolchain: str,
    binaries: ToolchainBinaries,
    timeout_sec: int = 5,
) -> tuple[bool, str, bool]:
    """
    Run the compiled binary in the simulator (QEMU or FVP).
    Returns (success: bool, output: str, timed_out: bool)
    """
    print(f"\n[Simulator] Running {elf_file} using {toolchain} (Timeout: {timeout_sec}s)...")

    if toolchain == "ds5":
        cmd = [
            binaries.fvp_bin,
            "-C",
            "cluster0.NUM_CORES=1",
            "--application",
            elf_file,
        ]
    else:
        cmd = [
            "qemu-system-arm",
            "-M",
            "versatilepb",
            "-m",
            "128M",
            "-nographic",
            "-kernel",
            elf_file,
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        output = result.stdout + result.stderr
        print("[Simulator] Finished Execution naturally.")
        return True, output, False
    except subprocess.TimeoutExpired as e:
        output = str(e.stdout or "") + str(e.stderr or "")
        print(f"[Simulator] Timeout! Execution exceeded {timeout_sec} seconds.")
        return True, output, True
    except Exception as e:
        return False, str(e), False
