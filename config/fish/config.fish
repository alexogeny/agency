# Keep CachyOS's useful defaults, then layer our portable preferences on top.
source /usr/share/cachyos-fish-config/cachyos-config.fish

set -gx EDITOR nano
set -gx VISUAL $EDITOR
set -gx PAGER less
set -gx LESS '-FRX'
set -gx CARGO_TERM_COLOR always

fish_add_path --prepend "$HOME/.local/bin" "$HOME/.cargo/bin" "$HOME/.bun/bin"

# Interactive quality-of-life without slowing non-interactive Fish invocations.
if status is-interactive
    set -g fish_greeting
    set -g fish_color_command ff79c6
    set -g fish_color_param f8f8f2
    set -g fish_color_option bd93f9
    set -g fish_color_error ff5555
    set -g fish_color_quote f1fa8c
    set -g fish_color_autosuggestion 6272a4

    abbr --add --position command g git
    abbr --add --position command ga 'git add'
    abbr --add --position command gd 'git diff'
    abbr --add --position command gs 'git status --short --branch'
    abbr --add --position command lg 'lazygit'
    abbr --add --position command ls 'eza --group-directories-first'
    abbr --add --position command ll 'eza --long --all --group-directories-first --git'
    abbr --add --position command tree 'eza --tree --group-directories-first'
    abbr --add --position command oldtasks 'long-processes'

    # `gcl owner/repo` clones or updates ~/Code/repo, then enters it.
    function gcl --description 'Clone or update a repository under ~/Code'
        set --local destination (git-get $argv)
        and cd "$destination"
    end

    function gpl --description 'Safely fast-forward a repository'
        if test (count $argv) -eq 0
            set --local branch (git symbolic-ref --quiet --short HEAD)
            if test -z "$branch"
                git pull --ff-only
                return
            end

            set --local remote (git config --get "branch.$branch.remote")
            set --local merge_ref (git config --get "branch.$branch.merge")
            set --local tracking_missing false

            if test "$remote" = .
                git pull --ff-only
                return
            end

            if test -z "$remote"
                set tracking_missing true
                set --local remotes (git remote)
                if contains -- origin $remotes
                    set remote origin
                else if test (count $remotes) -eq 1
                    set remote $remotes[1]
                else
                    git pull --ff-only
                    return
                end
            end

            if test -z "$merge_ref"
                set tracking_missing true
                set merge_ref "refs/heads/$branch"
            end

            git fetch --prune "$remote"
            or return

            set --local upstream_branch (string replace -- 'refs/heads/' '' "$merge_ref")
            set --local upstream_ref "refs/remotes/$remote/$upstream_branch"

            if not git show-ref --verify --quiet "$upstream_ref"
                set --local default_ref (git symbolic-ref --quiet "refs/remotes/$remote/HEAD")
                if test -n "$default_ref"; and not git show-ref --verify --quiet "$default_ref"
                    set --erase default_ref
                end

                if test -z "$default_ref"
                    for candidate in main master
                        set --local candidate_ref "refs/remotes/$remote/$candidate"
                        if git show-ref --verify --quiet "$candidate_ref"
                            set default_ref "$candidate_ref"
                            break
                        end
                    end
                end

                if test -z "$default_ref"
                    printf "Upstream '%s/%s' was deleted, but the remote's default branch could not be found.\n" "$remote" "$upstream_branch" >&2
                    return 1
                end

                set --local default_branch (string replace -- "refs/remotes/$remote/" '' "$default_ref")
                set --local local_default_ref "refs/heads/$default_branch"
                if git show-ref --verify --quiet "$local_default_ref"
                    if not git merge-base --is-ancestor "$local_default_ref" "$default_ref"
                        printf "Local branch '%s' has diverged from '%s/%s'; refusing to switch.\n" "$default_branch" "$remote" "$default_branch" >&2
                        return 1
                    end

                    set --local local_default_oid (git rev-parse "$local_default_ref")
                    or return
                    set --local remote_default_oid (git rev-parse "$default_ref")
                    or return
                    git update-ref -m "gpl: fast-forward to $remote/$default_branch" "$local_default_ref" "$remote_default_oid" "$local_default_oid"
                    or return
                end

                if test "$tracking_missing" = true
                    printf "Remote branch '%s/%s' does not exist; switching to '%s'.\n" "$remote" "$upstream_branch" "$default_branch"
                else
                    printf "Upstream '%s/%s' was deleted; switching to '%s'.\n" "$remote" "$upstream_branch" "$default_branch"
                end

                if git show-ref --verify --quiet "$local_default_ref"
                    git switch "$default_branch"
                else
                    git switch --track "$remote/$default_branch"
                end
                or return

                set upstream_ref "$default_ref"
            end

            git merge --ff-only "$upstream_ref"
        else
            set --local destination (git-get $argv)
            and cd "$destination"
        end
    end

    zoxide init fish | source
    direnv hook fish | source
    starship init fish | source
end
