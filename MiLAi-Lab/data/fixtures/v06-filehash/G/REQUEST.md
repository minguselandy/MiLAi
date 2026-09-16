# Filehash milestone

Implement `filehash.py`, a Python 3 command-line utility using only the standard library.
Invocation: `python3 filehash.py FILE [FILE ...]`.

For every input argument, write one JSON object on its own stdout line. A successful
record has exactly `path` and `sha256`; `path` is the argument as supplied, and
`sha256` is the lowercase SHA-256 digest of the file's binary contents. Preserve
argument order and duplicate arguments. Write Unicode paths without ASCII escaping.

If a file cannot be read, output a record with exactly `path` and `error`, then continue
with later arguments. The error must be a nonempty string. Exit 1 if any file fails,
otherwise exit 0. Do not change the working directory or modify input files.

Deliver the implementation, standard-library unittest tests and a short README with
invocation examples. Execute your tests. This milestone will have follow-up work.
The project uses the configured private working memory for continuity; retain useful
constraints, decisions and unfinished work when there is something worth carrying on.
Choose the memory representation yourself.
