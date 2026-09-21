from src.flakes.models import FlakeSource, FlakeOutput, InstallationPlan

def build_plan(
    source: FlakeSource,
    output: FlakeOutput,
    system: str,
) -> InstallationPlan:
    """Build an installation plan from a discovered flake output.
    
    The planner's job is to decide WHAT action should happen for a given output.
    It does not decide HOW — that's the executor's job. This separation lets
    the executor handle transaction mechanics (backup/rollback) uniformly
    regardless of the action type.
    
    The mapping here is intentionally simple: each output type maps to exactly
    one action. homeManagerModules maps to "configure_home" which the executor
    currently treats as a no-op guard — full Home Manager support is planned
    but not yet implemented.
    """
    if output.type in {"packages", "legacyPackages"}:
        action = "install"
    elif output.type == "nixosModules":
        action = "configure"
    elif output.type == "homeManagerModules":
        action = "configure_home"
    elif output.type == "overlays":
        action = "overlay"
    elif output.type in {"apps", "devShells"}:
        action = "unsupported"
    else:
        action = "unsupported"

    flake_name = source.url.split("/")[-1].split("?")[0]

    return InstallationPlan(
        source=source,
        output=output,
        action=action,
        system=system,
        flake_name=flake_name,
    )