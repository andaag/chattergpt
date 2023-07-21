{ pkgs, ... }:

{
  dotenv.enable = true;
  pre-commit.hooks.black.enable = true;
  pre-commit.hooks.shellcheck.enable = true;
  pre-commit.hooks.secret-scan = {
    enable = true;
    name = "Secret scanner";
    entry = "grep -qv 'private_key'";
    files = ".*";
    language = "system";
    pass_filenames = true;
  };


  languages.python.enable = true;
  languages.python.package = pkgs.python311;
  languages.python.poetry.enable = true;

  # https://devenv.sh/packages/
  packages = [ pkgs.git ];

  # https://devenv.sh/scripts/
  scripts.hello.exec = "echo Environment configured. You can use vscode . to open - or install mkhl.direnv in vscode.";

  enterShell = ''
    hello
  '';

  # https://devenv.sh/languages/
  # languages.nix.enable = true;

  # https://devenv.sh/pre-commit-hooks/
  # pre-commit.hooks.shellcheck.enable = true;

  # https://devenv.sh/processes/
  # processes.ping.exec = "ping example.com";

  # See full reference at https://devenv.sh/reference/options/
}
