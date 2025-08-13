# _XamGuard_

XamGuard is a lightweight, OOP-structured productivity blocker for Windows.  
It helps you stay focused by blocking distracting websites and applications on a schedule or on-demand — all while keeping a clean, modular codebase that’s easy to extend.

- Block websites or apps with a single command  
- Schedule focus sessions  
- Keep track of blocked apps in a simple SQLite database  
- _GOAL_: Minimal overhead, maximum focus

## Features

- Add/remove websites and applications from the blocklist
- Persistent blocklist storage via SQLite
- Scheduled blocking and unblocking
- Manual focus session trigger
- Command-line interface (CLI) for quick control
- Modular OOP design for easy future upgrades

## Tech

XamGuard is powered by a combination of Python and SQLite, leveraging clean architecture principles:

- [Python 3.10+] - modern programming language for simplicity and power
- [SQLite3] - lightweight database for storing blocklists
- [Schedule] - elegant job scheduling for timed blocking
- [psutil] - cross-platform process management
- [Pathlib] - modern path handling
- [pytest] - lightweight testing framework for Python

XamGuard is open source with a [public repository](https://github.com/raullucas7/XamGuard) on GitHub.

## Installation

XamGuard requires Python 3.10 or later.

Clone the repository and install dependencies:

```sh
git clone https://github.com/raullucas7/XamGuard.git
cd XamGuard
pip install -r requirements.txt
