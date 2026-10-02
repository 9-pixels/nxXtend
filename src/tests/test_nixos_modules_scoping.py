"""Tests for NixOS module scoping in flake.nix.

Verifies that add_flake_module correctly locates the
modules = [ ... ] list inside the selected nixosSystem and does not
accidentally write into unrelated modules lists.
"""

from core.writer import (
    add_flake,
    add_flake_module,
    _find_nixos_modules_list,
)


MODULE_LINE = "codex-desktop-linux.nixosModules.default"


def make_flake(
    modules_content,
    config_name="nixos",
    nixos_system="nixpkgs.lib.nixosSystem",
):
    """Build a minimal flake.nix with a nixosConfigurations block."""
    return (
        "{\n"
        "  inputs = {};\n"
        "  outputs = { nixpkgs, ... }:\n"
        "  {\n"
        f"    nixosConfigurations.{config_name} = {nixos_system} {{\n"
        '      system = "x86_64-linux";\n'
        f"      modules = {modules_content};\n"
        "    };\n"
        "  };\n"
        "}\n"
    )


def test_single_nixos_configuration():
    """A qualified nixosSystem should receive the module."""
    flake = make_flake("[ ./configuration.nix ]")

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert MODULE_LINE in result
    assert "./configuration.nix" in result

    found = _find_nixos_modules_list(flake, None)

    assert found is not None

    _, list_open, list_close = found

    assert flake[list_open] == "["
    assert flake[list_close] == "]"


def test_bare_nixos_system():
    """A bare nixosSystem should also be recognized."""
    flake = make_flake(
        "[ ./conf.nix ]",
        nixos_system="nixosSystem",
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert MODULE_LINE in result


def test_multiple_nixos_configurations_defaults_to_first():
    """Without target_config, only the first configuration is modified."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.foo = nixpkgs.lib.nixosSystem {\n"
        "      modules = [ ./foo.nix ];\n"
        "    };\n"
        "    nixosConfigurations.bar = nixpkgs.lib.nixosSystem {\n"
        "      modules = [ ./bar.nix ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert result.count(MODULE_LINE) == 1

    foo_section = result[
        result.index("nixosConfigurations.foo"):
        result.index("nixosConfigurations.bar")
    ]
    bar_section = result[result.index("nixosConfigurations.bar"):]

    assert MODULE_LINE in foo_section
    assert MODULE_LINE not in bar_section


def test_target_config_selects_specific_configuration():
    """target_config should select the requested configuration."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.foo = nixpkgs.lib.nixosSystem {\n"
        "      modules = [ ./foo.nix ];\n"
        "    };\n"
        "    nixosConfigurations.bar = nixpkgs.lib.nixosSystem {\n"
        "      modules = [ ./bar.nix ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
        target_config="bar",
    )

    assert result.count(MODULE_LINE) == 1

    foo_section = result[
        result.index("nixosConfigurations.foo"):
        result.index("nixosConfigurations.bar")
    ]
    bar_section = result[result.index("nixosConfigurations.bar"):]

    assert MODULE_LINE not in foo_section
    assert MODULE_LINE in bar_section


def test_stray_modules_list_outside_nixos_system_is_ignored():
    """Unrelated modules lists must not be targeted."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    someOtherThing = {\n"
        "      modules = [\n"
        "        ./something.nix\n"
        "      ];\n"
        "    };\n"
        "    nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {\n"
        "      modules = [\n"
        "        ./configuration.nix\n"
        "      ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert MODULE_LINE in result

    some_other = result[
        result.index("someOtherThing"):
        result.index("nixosConfigurations")
    ]

    assert MODULE_LINE not in some_other


def test_duplicate_module_is_not_added_twice():
    """Adding an existing module must be idempotent."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {\n"
        "      modules = [ ./configuration.nix ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    first = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )
    second = add_flake_module(
        first,
        "codex-desktop-linux",
        "default",
    )

    assert second.count(MODULE_LINE) == 1
    assert second == first


def test_missing_nixos_system_is_fail_safe():
    """No nixosSystem means no mutation."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.nixos = { };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert result == flake


def test_non_nixos_system_function_is_fail_safe():
    """An unrelated function must not be treated as nixosSystem."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.nixos = someFunc {\n"
        "      x = 1;\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert result == flake


def test_comments_and_strings_do_not_confuse_scoping():
    """Commented or inline fake modules lists must be ignored."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        '    # modules = [ "fake" ];\n'
        "    nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {\n"
        '      modules = [ ./configuration.nix ];  # modules = [ "inline" ]\n'
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert MODULE_LINE in result
    assert '# modules = [ "fake" ];' in result


def test_nested_braces_inside_nixos_system_are_handled():
    """Nested attrsets must not terminate the nixosSystem search early."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {\n"
        '      system = "x86_64-linux";\n'
        "      specialArgs = {\n"
        "        foo = {\n"
        '          bar = "baz";\n'
        "        };\n"
        "      };\n"
        "      modules = [\n"
        "        ./configuration.nix\n"
        "      ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert MODULE_LINE in result
    assert "specialArgs" in result
    assert 'bar = "baz"' in result


def test_empty_modules_list():
    """An empty modules list should receive the module."""
    flake = make_flake("[ ]")

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert MODULE_LINE in result
    assert "];" in result


def test_whitespace_around_configuration_dot_is_supported():
    """Whitespace around the nixosConfigurations dot is tolerated."""
    flake = (
        "{\n"
        "  outputs = ... :\n"
        "  {\n"
        "    nixosConfigurations . nixos = nixpkgs.lib.nixosSystem {\n"
        "      modules = [ ./configuration.nix ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
    )

    assert MODULE_LINE in result


def test_add_flake_passes_target_config_through():
    """add_flake should propagate target_config to module insertion."""
    flake = make_flake("[ ./configuration.nix ]")

    flake_content, home_content, status = add_flake(
        flake_content=flake,
        flake_name="codex-desktop-linux",
        flake_url="github:codex-desktop-linux/flake",
        pkg_attr="default",
        pkg_type="nixosModule",
        module_name="default",
        target_config="nixos",
    )

    assert status == "success"
    assert MODULE_LINE in flake_content
    assert "codex-desktop-linux" in flake_content
    assert "url" in flake_content


def test_nonexistent_target_config_is_fail_safe():
    """An unknown target_config must not mutate the flake."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.foo = nixpkgs.lib.nixosSystem {\n"
        "      modules = [ ./foo.nix ];\n"
        "    };\n"
        "    nixosConfigurations.bar = nixpkgs.lib.nixosSystem {\n"
        "      modules = [ ./bar.nix ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(
        flake,
        "codex-desktop-linux",
        "default",
        target_config="does_not_exist",
    )

    assert result == flake


# ══════════════════════════════════════════════════════════════════════════
# Formatting regression tests
#
# The insertion used to copy the indentation of the *last* line inside the
# list.  When the last element was a nested attrset, that line was its
# closing `}`, so the module landed far too deep, and because that line's
# leading whitespace was consumed by the new element, the closing `];`
# collapsed to column 0.
# ══════════════════════════════════════════════════════════════════════════


def _nested_attrset_last_flake():
    """A realistic flake whose final modules entry is a nested attrset."""
    return (
        "{\n"
        "  inputs = {};\n"
        "  outputs = { nixpkgs, ... }:\n"
        "  {\n"
        "    nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {\n"
        '      system = "x86_64-linux";\n'
        "      modules = [\n"
        "        ./configuration.nix\n"
        "        home-manager.nixosModules.home-manager\n"
        "        {\n"
        "          home-manager.useGlobalPkgs = true;\n"
        "          home-manager.useUserPackages = true;\n"
        "        }\n"
        "      ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )


def test_module_line_matches_sibling_element_indentation():
    """The new module must line up with the other list elements."""
    result = add_flake_module(
        _nested_attrset_last_flake(),
        "codex-desktop-linux",
        "default",
    )

    lines = result.split("\n")
    module_line = next(l for l in lines if "codex-desktop-linux" in l)

    assert module_line == f"        {MODULE_LINE}"

    # Same leading whitespace as the sibling `./configuration.nix` entry.
    sibling = next(l for l in lines if "./configuration.nix" in l)
    assert (
        len(module_line) - len(module_line.lstrip())
        == len(sibling) - len(sibling.lstrip())
    )


def test_closing_bracket_keeps_its_indentation():
    """`];` must not collapse to column 0 after insertion."""
    result = add_flake_module(
        _nested_attrset_last_flake(),
        "codex-desktop-linux",
        "default",
    )

    assert "\n];" not in result, "closing bracket must not reach column 0"

    lines = result.split("\n")
    close_line = next(l for l in lines if l.strip() == "];")
    assert close_line == "      ];"


def test_nested_attrset_before_insertion_does_not_skew_indentation():
    """A `}` immediately before the new element must not leak its indentation."""
    result = add_flake_module(
        _nested_attrset_last_flake(),
        "codex-desktop-linux",
        "default",
    )

    # The exact defect that was observed: closing brace followed by an
    # over-indented module line.
    assert "}\n              codex-desktop-linux" not in result
    # The module sits at element indentation (optionally after a blank line).
    assert "        codex-desktop-linux.nixosModules.default" in result
    assert "\n              codex" not in result


def test_blank_line_separates_attrset_element_from_new_module():
    """A multi-line attrset element is followed by a blank line, then the module."""
    result = add_flake_module(
        _nested_attrset_last_flake(),
        "codex-desktop-linux",
        "default",
    )

    assert "        }\n\n        codex-desktop-linux.nixosModules.default" in result


def test_existing_formatting_is_preserved():
    """Only the new element and the closing line may change."""
    flake = _nested_attrset_last_flake()
    result = add_flake_module(flake, "codex-desktop-linux", "default")

    for original_line in flake.split("\n"):
        if original_line.strip():
            assert original_line in result


def test_single_line_modules_list_stays_single_line():
    """A one-line modules list must not be exploded into multiple lines."""
    flake = make_flake("[ ./configuration.nix ]")
    result = add_flake_module(flake, "codex-desktop-linux", "default")

    assert f"modules = [ ./configuration.nix {MODULE_LINE} ];" in result
    assert result.count("\n") == flake.count("\n")


def test_nested_attrset_inside_special_args_before_modules():
    """Nested braces in specialArgs must not disturb module formatting."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {\n"
        "      specialArgs = {\n"
        "        foo = {\n"
        "          bar = true;\n"
        "        };\n"
        "      };\n"
        "      modules = [\n"
        "        ./configuration.nix\n"
        "      ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(flake, "codex-desktop-linux", "default")

    assert f"        {MODULE_LINE}" in result
    assert "\n];" not in result
    assert "      ];" in result


def test_deeper_indentation_is_respected():
    """Indentation is derived from the source, not hard-coded."""
    flake = (
        "{\n"
        "  outputs = { ... }:\n"
        "  {\n"
        "    nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {\n"
        "      modules = [\n"
        "            ./deep.nix\n"
        "      ];\n"
        "    };\n"
        "  };\n"
        "}\n"
    )

    result = add_flake_module(flake, "codex-desktop-linux", "default")

    assert f"            {MODULE_LINE}" in result
    assert "\n];" not in result