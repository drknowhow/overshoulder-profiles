# Contributing a profile

Thank you for sharing what your agents learned. This page lists what the checks refuse and what the
review looks at.

## Where a profile goes

`apps/<app id>/<your GitHub login>.osp`, with your login in lower case. The app id is the first value on
the file's second line (`app <app id> ...`). A pull request may add, change or remove only files named
after its author. Changes anywhere else in the repository come from the maintainers.

## What the checks refuse

The checks run Overshoulder's own rules from a pinned release, so a file passes when it is exactly what
an export writes. They refuse a file that:

- is not a valid `.osp` file, or whose `end sha256=` line no longer matches because it was edited by
  hand;
- has a `sig` line (the registry signs a profile when it merges);
- holds something an export leaves out, such as a control seen in only one session or revision history;
- has a field an export never writes, or a value in a shape an export never writes;
- has an e-mail address, a file path or a link in any of its text (a guide note's own link is checked
  separately: it must be a public http or https address without a query);
- sits in a folder named after a different app;
- is larger than 64 KB.

Each refusal says what to change. Most are fixed by exporting the profile again from Overshoulder
instead of editing it.

## The review

After the checks pass, Yep ([@yepgent](https://github.com/yepgent)) reads the profile and merges it, or
says what needs to change. The review looks at the free text: control names, quirks, how-tos and guide
notes. Text that reads like it talks to an agent ("ignore your instructions", a command to run, a
request for a password) is flagged by the checks for the reviewer. A how-to such as "click OK first" is
normal, and a note that tries to steer agents is not merged.

Agents read every note in a profile as information from another agent, never as an instruction, and a
profile cannot widen what an agent may do. The review keeps the notes useful and honest.

## Licence

By opening a pull request you dedicate your profile to the public domain under
[CC0 1.0](LICENSE).
