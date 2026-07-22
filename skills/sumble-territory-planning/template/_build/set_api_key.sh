#!/bin/sh
# Save your Sumble API key to ~/.config/sumble/api_key (chmod 600).
#
# Pure POSIX shell — no Python required. Equivalent to set_api_key.py:
# prompts with hidden input (the key never lands in your terminal scrollback
# or shell history) and stores it where fetch_data.py / score_accounts.py
# look automatically.
#
# Usage:  sh set_api_key.sh
set -e

echo "Get your Sumble API key from: https://sumble.com/account (Account -> API key)"
printf "Paste your Sumble API key (input hidden): "

# Hide input; make sure echo is restored even on Ctrl-C.
stty_state=$(stty -g 2>/dev/null || true)
restore() { [ -n "$stty_state" ] && stty "$stty_state" 2>/dev/null || stty echo 2>/dev/null || true; }
trap restore EXIT INT TERM
stty -echo 2>/dev/null || true
IFS= read -r key
restore
printf "\n"

key=$(printf "%s" "$key" | tr -d '[:space:]')
if [ -z "$key" ]; then
  echo "No key entered — nothing saved." >&2
  exit 1
fi

dir="$HOME/.config/sumble"
mkdir -p "$dir"
umask 177
printf "%s\n" "$key" > "$dir/api_key"
chmod 600 "$dir/api_key"
echo "Saved to $dir/api_key (chmod 600). The pipeline scripts find it automatically."
