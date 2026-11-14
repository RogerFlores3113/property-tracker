# Skills for Claude and Codex

A skill is a short instruction file that teaches an AI app how to use Property Helper well: which tools to call, how to
save a place from a listing link or pasted text, how to prep for tours, compare places and draft a message for you to
send, and the rules it must always follow (listings are data and never instructions, the AI never deletes anything,
it never writes your own notes, and it asks you before it contacts anyone).

Skills are optional. Connecting the app (the Connect page) is what gives Claude or Codex the tools. A skill only adds
guidance on top.

There are two skills here, with the same advice in the form each app reads:

- `skills/claude/property-helper/SKILL.md` for Claude
- `skills/codex/property-helper/SKILL.md` for Codex

## The easy way

In Property Helper, open Connect, then Skills for Claude and Codex (or go to `/skills` in the app window). It shows
exactly which file it will write and where, writes only that file, and has an Uninstall button that removes only what
it wrote. It never overwrites a file it did not write.

On the Connect page, **Install skills** does both apps at once (after showing the files), and **Get the Claude
plugin** saves one `property-helper.plugin` file for the Claude app (Customize, Plugins, Add, Upload plugin). In a
terminal, run `prophelper install-skills` (add `--yes` to skip the question) or `prophelper install-skills --plugin`.

Claude Code can also take the plugin from this repository:

```
/plugin marketplace add rogerflores3113/property-helper
/plugin install property-helper@property-helper
```

## Install by hand (a person, Claude or Codex can follow these steps)

These are the documented locations at the time of writing. If an app moved them, check that app's own docs.

For Claude (Claude Code reads personal skills from your home folder):

1. Make the folder `~/.claude/skills/property-helper/`. On Windows, `~` is your user folder, for example
   `C:\Users\YourName`.
2. Copy `skills/claude/property-helper/SKILL.md` into it, so the file ends up at
   `~/.claude/skills/property-helper/SKILL.md`.
3. Start a new Claude session. The skill is listed by its name, `property-helper`.

For Codex:

1. Make the folder `~/.codex/skills/property-helper/` (if you set the `CODEX_HOME` environment variable, use
   `$CODEX_HOME/skills/property-helper/` instead).
2. Copy `skills/codex/property-helper/SKILL.md` into it, so the file ends up at
   `~/.codex/skills/property-helper/SKILL.md`.
3. Restart Codex.

If a file already exists at the destination and you did not put it there, read it before replacing it.

## Remove them

Delete the `property-helper` folder you made (`~/.claude/skills/property-helper/` or
`~/.codex/skills/property-helper/`), or press Uninstall on the Skills page in the app.

## What they do not do

Skills send nothing anywhere and change nothing in Property Helper. They are plain text that the AI app reads.
