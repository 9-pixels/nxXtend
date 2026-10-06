<div align="center">

<h1>nx</h1>

[![License](https://img.shields.io/github/license/9-pixels/nxXtend)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-551%20passing-success)](#testing)
[![Python](https://img.shields.io/badge/Python-3.x-blue?logo=python)](https://www.python.org/)
[![NixOS](https://img.shields.io/badge/NixOS-supported-5277C3?logo=nixos)](https://nixos.org/)

<p><em>Because you're not ready to type the full name every time.</em></p>

<!-- badges -->

<p>
  <a href="#features">Features</a> |
  <a href="#installation">Installation</a> |
  <a href="#usage">Usage</a> |
  <a href="#architecture">Architecture</a>
</p>

</div>

## What is nx(Xtend)

`nx` is an attempt to automate package installation workflows in NixOS while respecting the principles of transparency and information sharing that have long been part of the NixOS community.

The tool allows users to modify the core NixOS configuration files, such as `flake.nix`, `home.nix`, and `configuration.nix`, while leaving other customizations and sensitive configuration untouched.

There are still parts of the tool that are incomplete, making it inaccurate to claim that `nx` fully upholds these principles yet. This is one of the reasons why `nx` is still in beta.

## Features

### Package Management

- Install and manage packages from both `stable` and `unstable` `nixpkgs`.
- Search for packages and select the desired source interactively.
- Upgrade or remove installed packages.

### Flake Management

- Inspect Flakes using `nix flake metadata` and `nix flake show`.
- Discover and classify Flake outputs before modifying the system configuration.
- Install and integrate the currently supported output types:
    - `packages`
    - `legacyPackages`
    - `nixosModules`
    - `overlays`
- Detect additional output types such as `apps`, `devShells`, and `homeManagerModules`, but leave unsupported outputs unchanged.
- Present the selected Flake output and planned changes before modifying system files.
- Create backups before applying Flake changes and restore them if the resulting system rebuild fails.
- Flake support is still experimental and does not guarantee a stable workflow for every repository. Flakes can expose different output structures, so support is limited to explicitly handled output types.

### Configuration & Safety

- Customize `nx` preferences and NixOS file paths through `nx setup`.
- Modify supported system configuration files while leaving unrelated customizations untouched.
- Create backups before modifying system files and automatically restore them when a build fails.

## Installation

`nx` can be installed in several ways, depending on how you want to use it.

### Using the installer

The recommended way to install a released version is:

```bash
curl -fsSL https://raw.githubusercontent.com/9-pixels/nxXtend/main/install.sh | bash
```

The installer downloads the latest release, creates an isolated Python environment, and makes `nx` available through `~/.local/bin`.

Verify the installation with:

```bash
nx --version
nx --help
```

If `~/.local/bin` is not in your `PATH`, add it to your shell environment before using `nx` directly.

### Using Nix

If you already use Nix, `nx` can be built directly from its flake:

```bash
nix build github:9-pixels/nxXtend
```

For a local checkout:

```bash
nix build
```

The resulting executable is available at:

```text
./result/bin/nx
```

### Using Nix Flakes

If your NixOS system is managed with a flake, add `nxXtend` as an input:

```nix
inputs = {
  nxXtend = {
    url = "github:9-pixels/nxXtend";
    inputs.nixpkgs.follows = "nixpkgs";
  };
};
```

Then add the `nx` package to your system configuration:

```nix
environment.systemPackages = [
  inputs.nxXtend.packages.${pkgs.stdenv.hostPlatform.system}.default
];
```

After rebuilding your system, `nx` will be available as a system package.

This method keeps `nxXtend` managed declaratively alongside the rest of your NixOS configuration.

### From source

For development or contributors, clone the repository and install it from source:

```bash
git clone https://github.com/9-pixels/nxXtend.git
cd nxXtend

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then verify:

```bash
nx --version
```

## Usage

After installing `nx`, the first step is to run:

```bash
nx setup
```

This guides you through the initial configuration of `nx`, including your preferred way of working with NixOS and Flakes, as well as the paths to the main configuration files used by the system.

The configuration can be changed later by running `nx setup` again, or manually by editing `config.toml`.

### Commands

| Command                   | Description                                           |
| ------------------------- | ----------------------------------------------------- |
| `nx setup`                | Interactive first-time configuration                  |
| `nx install <package>`    | Install a package from nixpkgs                        |
| `nx remove <package>`     | Remove a package                                      |
| `nx upgrade`              | Rebuild and switch to the current NixOS configuration |
| `nx flakes <url>`         | Install from a Flake URL                              |
| `nx flakes install <url>` | Explicit Flake install                                |
| `nx flakes remove <name>` | Remove a Flake                                        |
| `nx flakes upgrade`       | Upgrade all Flakes                                    |
| `nx flakes update`        | Synonym for `upgrade`                                 |
| `nx --version` / `nx -v`  | Show version                                          |

**_(Honestly, I have no idea why I added this command if all it does is rebuild the system, but oh well, haha.)_**

### Short flags

Every command has a short form:

| Short | Long      |
| ----- | --------- |
| `-i`  | `install` |
| `-r`  | `remove`  |
| `-u`  | `upgrade` |
| `-f`  | `flakes`  |

Short flags are **composable** — they can appear in any order:

```bash
nx -i firefox              # install firefox
nx -r firefox              # remove firefox
nx -u                      # upgrade
nx -f github:x/y           # flakes install
nx -f -i github:x/y        # flakes install (explicit)
nx -f -r myflake           # flakes remove
nx -f -u                   # flakes upgrade
```

### The `-H` flag (Home Manager)

`-H` targets `home.nix` (`home.packages`) instead of `configuration.nix` (`environment.systemPackages`). It has **three spellings** and can appear **anywhere** among the flags:

```bash
nx install -H firefox
nx install --home firefox
nx install -home firefox

nx -i -H firefox
nx -H -i firefox
nx -f -H github:x/y
nx -H -f github:x/y
```

**`-H` is rejected** for commands that cannot target Home Manager:

```bash
nx upgrade -H          # rejected — rebuild is system-wide
nx flakes upgrade -H   # rejected — rebuild is system-wide
```

### Global flags

| Flag              | Description  |
| ----------------- | ------------ |
| `-h`, `--help`    | Show help    |
| `--version`, `-v` | Show version |

### Exit codes

| Code | Meaning                                      |
| ---- | -------------------------------------------- |
| `0`  | Success, help, or version display            |
| `1`  | Operation rejected (e.g. `-H` on `upgrade`)  |
| `2`  | Invalid command or missing required argument |

<details>
<summary><h2>Architecture</h2></summary>

`nx` is organized into several components with separate responsibilities. The project is designed to keep user interaction, package discovery, Flake processing, configuration management, and Nix file modification separated rather than placing all logic in the CLI entry point.

### High-level structure

```text
User
 │
 ▼
main.py
 │
 ├── Package workflow
 │     │
 │     ├── core.manager
 │     │       ├── api.stable
 │     │       └── api.unstable
 │     │
 │     ├── core.target
 │     │
 │     ├── ui.display
 │     │
 │     └── core.writer
 │
 └── Flake workflow
       │
       ├── flakes.resolver
       ├── flakes.discovery
       ├── flakes.planner
       ├── core.target
       ├── ui.display
       └── flakes.executor
                │
                └── core.writer
```

Both workflows share `core.writer` and `ui.display`. The `core.target` module is used by both to resolve whether an operation targets `configuration.nix` (SYSTEM) or `home.nix` (HOME).

### Core components

#### `main.py`

The main entry point of `nx`.

It handles CLI commands and coordinates the high-level workflows. It does not directly implement the low-level Nix file manipulation, instead delegating those operations to the appropriate components.

#### `src/api/`

Provides access to package information from nixpkgs sources via the search.nixos.org Elasticsearch backend.

- `stable.py` handles stable package searches.
- `unstable.py` handles unstable package searches.
- `api_config.py` defines the Elasticsearch endpoint URLs and shared public credentials (same ones used by `nh` and other Nix tools).

The API layer is concerned with retrieving package information, not modifying the user's NixOS configuration.

#### `src/core/`

Contains functionality shared by the main system workflows.

- `config.py` manages `nx` configuration.
- `manager.py` coordinates package searches across stable and unstable sources.
- `target.py` resolves whether an operation targets `configuration.nix` (SYSTEM) or `home.nix` (HOME). It separates **where** a package is placed from **where** it comes from (nixpkgs vs Flake). Pure function — no I/O, no config mutation.
- `writer.py` performs the actual modification of Nix configuration files and provides backup and restoration functionality.

The writer is intentionally kept separate from decision-making logic: it knows how to modify configuration files, while higher-level components decide what should be changed.

#### `src/flakes/`

Contains the Flake-specific processing pipeline.

```text
Resolver
   ↓
Discovery
   ↓
Planner
   ↓
Executor
   ↓
Writer
```

- **Resolver** resolves the Flake source and retrieves relevant metadata.
- **Discovery** inspects the Flake and identifies usable outputs.
- **Planner** converts discovered outputs into actions.
- **Executor** performs those actions and coordinates the transaction, including backup, rebuild, and rollback.
- **Models** (`src/flakes/models.py`) defines the data structures used by the Flake workflow: `FlakeSource` (URL, revision, target), `FlakeOutput` (name, type, system, attribute), and `InstallationPlan` (source, output, action, system, flake_name).

This pipeline is specific to Flake processing and should not be interpreted as the complete architecture of `nx`.

#### `src/models/`

Contains shared data models used by the application.

- `package.py` defines the `Package` dataclass. It carries two distinct identities: `name` (upstream `package_pname`, display/metadata only) and `attribute` (canonical `package_attr_name`, used for every Nix reference, duplicate check, and collision check). These are frequently equal but never interchangeable — `pkgs.nx` and `pkgs.nxXtend` are different packages.

#### `src/ui/`

Contains user-facing interaction.

- `display.py` handles interactive selection and presentation.
- `first_setup.py` provides the initial setup wizard.

The UI is responsible for communicating with the user rather than implementing the underlying Nix operations.

### Configuration and Safety

`nx` keeps its own configuration separate from the NixOS configuration it manages.

When modifying system configuration, `nx` uses a backup and rollback mechanism so that failed rebuilds can restore the files modified by the operation.

This separation allows `nx` to act as a layer over NixOS without hiding the underlying Nix configuration from the user.

### Current Limitations

The current architecture is functional but still evolving.

The package workflow and Flake workflow do not yet share exactly the same execution pipeline. Some transaction and rebuild coordination currently remains in `main.py`, while Flake operations use the dedicated executor.

Some Flake output types are also only partially implemented. For example, planning support may exist for certain output types before their complete execution path is available.

These limitations are part of the current development state and may be addressed as the project moves toward `v1.0`.

</details>

<details>
<summary><h2>Flakes</h2></summary>

`nx` provides an experimental workflow for inspecting and integrating Flakes into a NixOS configuration.

Rather than treating a Flake as a simple URL to add to a configuration file, `nx` first inspects the Flake and determines what outputs it provides and how those outputs can be used by the system.

### Flake Discovery

When a Flake URL is provided, `nx` first resolves the source and retrieves its metadata using:

```bash
nix flake metadata --json
```

The metadata is used to identify the locked revision of the Flake.

`nx` then inspects the Flake's available outputs using:

```bash
nix flake show --json
```

The discovered outputs are classified according to their type and the current system architecture. Supported output categories include packages, legacy packages, NixOS modules, Home Manager modules, and overlays, while other output types may be identified but are not currently handled by the installation workflow.

### Planning

After discovery, `nx` presents the supported outputs to the user instead of assuming which part of the Flake should be installed.

The selected output is then converted into an installation plan. Depending on its type, the plan may represent a package installation, NixOS configuration, Home Manager configuration, or overlay integration.

The plan is shown to the user before any system files are modified.

### Integration

For supported Flake workflows, `nx` can integrate the selected output into the user's existing configuration.

This may involve modifying:

- `flake.nix`
- `flake.lock`
- `configuration.nix`
- `home.nix`

The writer operates on the relevant parts of these files rather than replacing the user's configuration as a whole. Flake inputs and output references are added using the structure expected by the current workflow.

For package outputs, `nx` supports the package references required by its current configuration formats, including references involving `pkgs` and configured `unstable` package sets.

### Rebuild and Rollback

After the required files are modified, `nx` rebuilds the system using the configured Flake.

Before modifying system files, the relevant files are backed up. If the rebuild fails, `nx` restores the previous files instead of leaving the configuration in the failed state.

This makes Flake integration a transactional workflow rather than simply writing text into a Nix file and hoping for the best.

### Current Limitations

Flake support is still experimental.

`nx` does not currently handle every possible Flake output or repository structure. Some output types are discovered but are not yet fully integrated into the execution layer, and Flakes with more complex structures may fall outside the cases currently supported by the writer.

In particular, support for Home Manager modules and some other output types is incomplete, while applications, development shells, and checks are not currently installation targets.

`nx` also makes assumptions about parts of the Flake structure, such as the relationship between `nixpkgs` and Flake inputs. Repositories using structures outside these assumptions may require manual integration.

For this reason, successful discovery of a Flake does not guarantee that every output provided by that Flake can be installed or integrated automatically.

The goal of the current implementation is not to hide the complexity of Flakes, but to make the parts that `nx` understands easier to inspect, select, and integrate while preserving the user's existing configuration.

</details>

<details>
<summary><h2>Backup & Rollback</h2></summary>

Before modifying system configuration files, `nx` creates backups under:

```text
/etc/nixos/.nx-backup/
```

If a rebuild fails, the files modified by the operation are restored from the backup.

This applies to the files involved in the current operation rather than replacing the entire NixOS configuration.

The mechanism is intended to provide a safety boundary around automatic modifications while keeping the underlying configuration available to the user.

Automatic rollback can also mean that a failed configuration is not left in place for debugging. This is a deliberate trade-off in the current design: the priority is to avoid leaving the system configuration in the state produced by a failed operation.

</details>

<details>
<summary><h2>Configuration</h2></summary>

`nx` stores its configuration in:

```text
~/.config/nx/config.toml
```

The configuration controls how `nx` interacts with the user's NixOS setup, including the paths of the main configuration files, Flake and Home Manager usage, and the name used for the `unstable` package set.

### `nx setup`

After installation, `nx setup` provides an interactive configuration wizard.

The wizard allows the user to configure:

- The path to `configuration.nix`
- Whether Flakes are enabled
- The path to `flake.nix`
- Whether Home Manager is enabled
- The path to `home.nix`
- The variable name used for `unstable` packages

The wizard also displays the resulting configuration before saving it.

`nx setup` can be run again later to change these settings. Existing values are used as the defaults during subsequent setup runs.

The configuration file may also be edited manually. Valid existing values are preserved when `nx` validates and repairs the configuration.

### Configuration Structure

The main user-configurable settings are stored under `[setup]`:

| Setting                | Description                                                                   |
| ---------------------- | ----------------------------------------------------------------------------- |
| `configuration_path`   | Path to the main `configuration.nix` file.                                    |
| `flake_enabled`        | Determines whether the system uses a Flake-based workflow.                    |
| `flake_path`           | Path to the system's `flake.nix`.                                             |
| `home_manager_enabled` | Determines whether Flake operations use Home Manager configuration.           |
| `home_manager_path`    | Path to `home.nix` when Home Manager is enabled.                              |
| `unstable_variable`    | Variable name used when referencing packages from the `unstable` package set. |

For example, with the default setting:

```toml
unstable_variable = "unstable"
```

an unstable package reference can use:

```nix
unstable.steam
```

The `[meta]` section contains internal state managed by `nx`, including:

```toml
setup_done = true
```

This value is used to determine whether the initial setup has been completed.

### Configuration Validation

`nx` validates the configuration whenever it is loaded.

If a setting is missing or invalid, `nx` repairs that setting using its default value while preserving valid user configuration.

This allows manually edited configuration files to remain usable without replacing the entire configuration.

The configuration template also contains sections reserved for future features. These sections are currently informational and are not used by the running workflows.

</details>

<details>
<summary><h2>Testing</h2></summary>

`nx` currently has a test suite covering its core components and workflows.

### Running the tests

The suite is a mix of two styles and needs **both** the repository root and `src/`
on `PYTHONPATH`:

```bash
cd /path/to/nxXtend
export PYTHONPATH="$PWD:$PWD/src"
```

Both entries are required because the tree mixes two import styles — test files
import `from src.core.writer import ...` (needs the repo root) while the modules
themselves import `from core.writer import ...` and `from flakes.models import ...`
(needs `src/`). With only one of them you get `ModuleNotFoundError` before a
single assertion runs.

`pytest` is not a declared dependency. Install it into your environment first:

```bash
pip install pytest
```

**Files that use `pytest`** (function-style, collected normally):

```bash
python -m pytest src/tests/test_backup_restore.py src/tests/test_config.py \
                 src/tests/test_discovery.py src/tests/test_executor.py \
                 src/tests/test_main.py src/tests/test_nixos_modules_scoping.py \
                 src/tests/test_package_attribute_identity.py \
                 src/tests/test_package_identity.py src/tests/test_planner.py \
                 src/tests/test_remove_flake.py src/tests/test_resolver.py
```

**Files that are standalone harnesses** (they call `sys.exit()` at the bottom, so
`pytest` aborts collection with `INTERNALERROR`). Run each one directly and read
its `RESULTS:` line:

```bash
for f in test_writer_formats test_writer_targets test_beta_audit_writer \
         test_beta_audit_flakes test_beta_audit_cli_config test_target \
         test_cli_shorts test_flakes_remove_target; do
    python "src/tests/$f.py"
done
```

Because of this split, running the whole `src/tests/` directory in a single
`pytest` call aborts on the first harness file. Pass explicit paths, and classify
a file before adding it to a batch run:

```bash
grep -q '^sys.exit' src/tests/test_<name>.py && echo harness || echo pytest
```

### Test Suite

The suite contains **19 test files**. The two styles are counted in **different
units** — a `pytest` run reports test _functions_, while a harness reports
`check()` _assertions_ — so they are listed in separate tables and must not be
added together.

**pytest-style files — 178 test functions total.** These are what
`python -m pytest` collects and reports.

| Test file                            | Test functions | Component                                       |
| ------------------------------------ | -------------: | ----------------------------------------------- |
| `test_package_identity.py`           |             32 | Package identity, duplicate/collision detection |
| `test_package_attribute_identity.py` |             28 | `package_attr_name` vs `package_pname` identity |
| `test_main.py`                       |             24 | CLI workflows and package operations            |
| `test_nixos_modules_scoping.py`      |             22 | Scoped `nixosModules` insertion                 |
| `test_executor.py`                   |             20 | Flake execution workflows                       |
| `test_remove_flake.py`               |             15 | Flake removal, backup, and rollback             |
| `test_config.py`                     |             12 | Configuration validation and repair             |
| `test_discovery.py`                  |              8 | Flake output discovery and classification       |
| `test_planner.py`                    |              8 | Action planning                                 |
| `test_resolver.py`                   |              5 | Resolver and metadata handling                  |
| `test_backup_restore.py`             |              4 | Backup and restore operations                   |
| **Total**                            |        **178** |                                                 |

**harness-style files — 377 `check()` assertions total.** Each file prints its own
`RESULTS: N passed, M failed` line.

| Test file                       | Assertions | Component                                   |
| ------------------------------- | ---------: | ------------------------------------------- |
| `test_writer_formats.py`        |        101 | Writer format contract and mutation gateway |
| `test_writer_targets.py`        |         86 | Writer target routing and list insertion    |
| `test_cli_shorts.py`            |         41 | Short-flag composition and dispatch wiring  |
| `test_flakes_remove_target.py`  |         28 | Target-aware Flake removal                  |
| `test_beta_audit_flakes.py`     |         36 | Flake audit findings                        |
| `test_beta_audit_cli_config.py` |         26 | CLI and config audit findings               |
| `test_target.py`                |         38 | SYSTEM/HOME target selection                |
| `test_beta_audit_writer.py`     |         21 | Writer audit findings                       |
| **Total**                       |    **377** |                                             |

The `test_beta_audit_*.py` files are audit harnesses: a failing check is a
**recorded finding**, not a broken test, so they exit 0 while documenting known
issues.

Across both styles: **551 passing, 4 failing**.

### Known failing tests

All 4 remaining failures are **recorded audit findings** in `test_beta_audit_flakes.py`
(3) and `test_beta_audit_cli_config.py` (1). They document known issues in the
error-handling paths and are intentional — the harness exits 0 while reporting them.

| Test file                       | Failing | Cause                                    |
| ------------------------------- | ------: | ---------------------------------------- |
| `test_beta_audit_flakes.py`     |       3 | Malformed JSON, duplicate input, rebuild |
| `test_beta_audit_cli_config.py` |       1 | Custom keys dropped during config repair |

**Previously fixed:** The `-H` routing failures (18 across `test_cli_shorts` and
`test_flakes_remove_target`) and the crashes in `test_target.py` and
`test_beta_audit_flakes.py` were caused by test files importing `Target` via
`from src.core.target import` while the application uses `from core.target import`.
Python loaded the same file twice under two module names, creating two distinct
`Target` classes. Aligning the import paths fixed all of them.

### Integration Testing

The test suite also covers complete workflows by connecting multiple parts of `nx` together.

The current integration coverage includes:

- Package installation and removal workflows.
- Backup before modification and restoration after failed rebuilds.
- Flake upgrade ordering, including updating the Flake before rebuilding.
- Flake rollback across multiple configuration files.
- Successful operations where changes must remain after a successful rebuild.

Rollback tests also verify that backed-up files can be restored to their previous contents.

### Real NixOS Testing

Automated tests cannot reproduce every condition of a real NixOS system. For that reason, `nx` has also been tested directly on NixOS.

A real package installation was tested using:

```bash
sudo python main.py install vmware-workstation
```

The `nx` workflow completed successfully through `nixos-rebuild switch`. VMware itself subsequently failed inside the virtual machine with:

```text
[AppLoader] libdir is not initialized...
```

This was an issue with VMware in the virtualized environment, not with the `nx` installation workflow.

Real Flake workflows have also been tested, including:

- Installing a Flake and adding its input and package reference.
- Removing a Flake and cleaning its references from the relevant configuration files.
- Running `nx setup` and verifying that the configuration wizard saves its settings correctly.

### Testing Methodology

Testing `nx` has involved two different approaches.

The core implementation and its internal edge cases were tested with the help of AI-generated and AI-executed tests. These tests cover components such as the resolver, discovery, planner, executor, writer, configuration system, and CLI workflows. System operations such as subprocess calls and file copying are mocked where appropriate so that individual behaviors can be tested in isolation.

The actual user experience was tested manually by the project developer on NixOS. This included running `nx setup`, installing and removing packages, working with Flakes, observing errors and output, and testing the tool in a real system environment.

This distinction is important: passing automated tests does not mean that `nx` has been fully validated as a real-world NixOS tool. The automated suite verifies controlled behavior, while real-system testing exposes issues that mocks and isolated tests cannot reproduce.

### Current Limitations

The test suite does not currently cover every part of the project.

There are currently no dedicated automated tests for:

- `src/ui/display.py`
- `src/ui/first_setup.py`
- Real API calls from `src/api/stable.py` and `src/api/unstable.py`
- Actual `nixos-rebuild` execution inside the automated test suite

The automated tests mock system-level operations such as subprocess execution and file copying. As a result, they verify how `nx` responds to those operations rather than validating every behavior of the underlying NixOS environment.

Real-system testing therefore remains an important part of validating `nx`, especially for workflows involving Nix, Flakes, system rebuilds, and filesystem changes.

</details>

## Roadmap

The roadmap below describes the current direction of `nx` rather than a fixed set of commitments. As the project develops, priorities and implementation details may change.

### Approaching v1.0

The current goal is to bring `nx` closer to a stable `v1.0`.

This stage focuses on:

- Fixing known bugs and edge cases.
- Completing the essential package and Flake workflows.
- Completing the integrations required by the current core workflows.
- Improving the reliability of backup, rebuild, and rollback operations.
- Expanding testing against real NixOS environments.
- Refining the current architecture where necessary.

The intention is to establish a reliable foundation before significantly expanding the project's scope.

### Post-v1.0 — Possible Directions

After reaching `v1.0`, development may gradually move toward features that expand what `nx` can remember, understand, and integrate with.

#### 1. NX Metadata Log

We are considering a local metadata log under:

```text
~/.config/nx/
```

The idea is to keep information about Flake repositories previously handled by `nx`, including metadata that may help the tool understand and update their integration later.

This could allow `nx` to reuse previously discovered information and refresh it when repositories change, rather than treating every update as a completely new discovery process.

#### 2. Shortcuts

Another possible direction is introducing shortcuts for frequently used package or configuration paths.

The goal would be to make complex NixOS configurations easier to navigate and manage without repeatedly searching through configuration files manually.

#### 3. Fullinfo

We may also explore a more comprehensive way of inspecting packages and information referenced by the system configuration.

The intention is to make information already available to `nx` easier to understand, potentially through structured output or tables instead of requiring users to inspect build files manually.

#### 4. Ecosystem Integrations

We may explore optional integrations with tools such as `nh` and other useful tools from the Nix ecosystem.

The intention is to complement existing tools rather than replace them, while keeping such integrations optional for users.

#### 5. nxflakerepo

A larger long-term idea is `nxflakerepo`, a shared repository for Flake metadata.

The concept is to allow `nx` to check whether useful metadata for a repository is already available before performing the normal discovery process:

```text
nx
 │
 ▼
Check nxflakerepo
 │
 ├── Metadata available
 │      └── Reuse known information
 │
 └── Metadata unavailable
        │
        ▼
     Normal discovery
        │
        ▼
     Successful integration
        │
        ▼
     Generate metadata
        │
        ▼
     Optionally contribute
```

If this direction proves useful, the repository could gradually become a shared source of previously discovered Flake information.

Participation would remain optional.

A major goal of this idea would be transparency. We would aim to clearly document what metadata is collected, why it is collected, how it is used, and what information may be shared.

The repository would be intended to complement the normal Flake discovery process rather than replace it. When shared metadata is unavailable, outdated, or unsuitable for the current situation, `nx` could fall back to its normal discovery workflow.

## Transparency

Yes, I do use AI in the development of `nx`. More specifically, I use Claude, ChatGPT, and Hermes Agent as part of my development workflow.

A significant portion of the code has been written with the help of these models, but the planning, architecture, project logic, and decisions behind the tool are mine. I am responsible for deciding what `nx` should do, how its components should interact, what problems it should solve, and how the project should evolve. The models assist me with the literal implementation of those ideas.

I have a reasonable level of experience with programming and can read and understand the code produced by these models, identify some mistakes, question their decisions, and test what they produce. However, I do not want to pretend that I currently understand every part of `nx` from beginning to end.

Why am I being explicit about this?

Because I am a NixOS user, or at least I am trying to be one, and one of the reasons I moved to this distribution is its emphasis on understanding and controlling what happens on my system. Hiding the role AI played in building `nx` would go against the principle that led me to use NixOS in the first place.

That does not mean I intend to leave the project in its current state.

The period between `v0.1` and the eventual stable `v1.0` is intentionally meant to include exactly this work: cleaning up the code, understanding the implementation more deeply, improving the architecture, making the tool safer when dealing with rare or unexpected situations, reducing the number of ways in which an operation can break, stabilizing the code, and making the features themselves more reliable.

Publishing `nx` as a beta is therefore also an honest statement about its current state. It is a working project, but it is not something I want to present as fully mature or completely understood when it is not.

Thank you for understanding and respecting this approach to development.

## License

`nx` is licensed under the GNU General Public License v3.0.

See the project's license file for the complete license text.
