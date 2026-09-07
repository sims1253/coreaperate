# Dependency notices

The project uses the repository's Apache-2.0 license. Third-party dependencies retain their own licenses, included in this directory; the Lua JSON module also carries its license in source.

Runtime: websockets 17.0.1 (BSD-3-Clause) and vendored dkjson 2.5 (MIT). Python, SQLite, and REAPER are supplied by the user. Test-only packages and their notices are included for Lupa 2.6, pytest 8.4.2, colorama 0.4.6, iniconfig 2.3.0, packaging 26.3, pluggy 1.6.0, and Pygments 2.21.0. Exact installation pins live in the dependency files.

dkjson was retrieved from <https://github.com/LuaDist/dkjson/blob/master/dkjson.lua>. The only source normalization for publication was removing a trailing blank line. SHA-256 of the shipped LF-normalized `reaper/lib/dkjson.lua`:

```text
c739f6eb61eaa666602e377c48656028775d188c2ad6d979ea1fdac8375d9834
```

License text was retained; line endings and a decorative heading underline in the Lupa notice were normalized for Git whitespace checks.
