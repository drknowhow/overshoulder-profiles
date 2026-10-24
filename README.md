# Overshoulder profiles

App profiles for [Overshoulder](https://github.com/drknowhow/overshoulder), shared by the people whose
agents learned them.

A profile is a small `.osp` text file about one Windows app: its windows and controls, which methods
work there, its shortcuts and quirks, and short how-tos. Overshoulder hands it to an agent when the agent
takes a window of that app, so the agent starts with what earlier agents learned. A profile is
information. It never lets an agent do more than you allow, and Overshoulder's rules are the same with
or without one.

## Use a profile

Download the `.osp` file and open it. Overshoulder shows what the profile holds, including any notes
other agents wrote, and adds nothing until you say yes. What your own PC has learned always wins over an
imported item.

## Publish yours

1. Export it from Overshoulder: `overshoulder profile export <app>`, or Export on the settings page. An
   export leaves out window titles, typed text, file names and anything seen in only one session.
2. Open a pull request that adds it at `apps/<app id>/<your GitHub login>.osp`, with your login in lower
   case. The app id is on the file's second line, after `app`.
3. The checks run on your pull request. Then Yep ([@yepgent](https://github.com/yepgent)) reviews it and
   merges it, and the registry signs it.

One profile per app per account: to update yours, change your file in a new pull request. You can
change or remove only your own files. [CONTRIBUTING.md](CONTRIBUTING.md) lists what the checks refuse.

## Signatures

When a pull request merges, the registry adds a line just above the file's last line:

```
sig registry key=reg-1 by=<login> pr=<number> at=<date> ed25519=<signature>
```

The signature covers every line of the profile, the publisher, the pull request and the date.
Overshoulder ships the registry's public key and refuses a signed file that was changed afterwards.
`overshoulder profile verify <file>` tells you who published a file and whether it is intact.

Key `reg-1`: `f9e83d9b1ec3045d0816e34d58ec77092daf9beaaf4cf808cdc30d13de87620a` (Ed25519).

The files in this repository are the ones people submitted, without signatures. The signed copies and
the catalog, `index.json` with its signature `index.json.sig`, are built on every merge.

## Licence

Profiles are dedicated to the public domain under [CC0 1.0](LICENSE). By opening a pull request you
dedicate your profile under CC0 1.0, so anyone may use it for anything.
