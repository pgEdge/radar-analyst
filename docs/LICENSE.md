The PostgreSQL License

Portions copyright (c) 2026, pgEdge, Inc.

Permission to use, copy, modify, and distribute this software and its
documentation for any purpose, without fee, and without a written agreement is
hereby granted, provided that the above copyright notice and this paragraph and
the following two paragraphs appear in all copies.

IN NO EVENT SHALL pgEdge, Inc. BE LIABLE TO ANY PARTY FOR DIRECT, INDIRECT,
SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES, INCLUDING LOST PROFITS, ARISING
OUT OF THE USE OF THIS SOFTWARE AND ITS DOCUMENTATION, EVEN IF pgEdge, Inc. HAS
BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

pgEdge, Inc. SPECIFICALLY DISCLAIMS ANY WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE. THE SOFTWARE PROVIDED HEREUNDER IS ON AN "AS IS" BASIS, AND pgEdge,
Inc. HAS NO OBLIGATIONS TO PROVIDE MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS,
OR MODIFICATIONS.

## Reviewing Python Package Licenses

The container image includes the license of every Python package that the
image installs. The `/usr/share/doc/radar-analyst/NOTICE.txt` file in the
image lists each package with the package's license text and any notice file
that the package includes.

The following command prints the file from the running analyst container:

```bash
docker compose exec app cat /usr/share/doc/radar-analyst/NOTICE.txt
```
