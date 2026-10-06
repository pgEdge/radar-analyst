# Using the Analyst

You assess a host by collecting a radar archive on the host and uploading the
archive to the analyst's console. This page describes the upload, the list of
assessments, assessing an upload again, and deleting an assessment.

## Collecting a Radar Archive

Radar collects the diagnostic archive on the PostgreSQL host. The archive
contains metadata about the machine and the server, never table contents or
query results. The
[Taking a Radar Collection](walkthrough.md#taking-a-radar-collection) section
of the walkthrough describes how to run radar on the host.

## Uploading an Archive

The console accepts one zip archive at a time. To assess an archive in the
console, perform the following steps:

1. Open [http://localhost:8080/](http://localhost:8080/) in a browser on the
   machine that runs the analyst.
2. Drag the radar archive onto the upload area, or click the upload area and
   choose the archive.
3. Select **Upload** to send the archive to the analyst.

The console shows the progress while the analyst reads the archive and assesses
each category. When the assessment finishes, the console opens the result. The
analyst accepts zip archives of up to 500 MiB and refuses any other file at
upload.

The analyst also limits what an archive may expand to, and the assessment fails
for an archive beyond any limit. The following table describes those limits:

| Limit | Value |
|---|---|
| Entries in the archive | 100,000 |
| Uncompressed size of a single entry | 500 MiB |
| Uncompressed size of all entries together | 2 GiB |

## Reading the List of Assessments

The front page of the console lists the 50 most recent uploads, newest first.
Each entry shows the host, the file name and size, the collection time, the
status, and the upload time. The status is the verdict, "Assessing…" while the
assessment runs, or "Failed" if the assessment fails. The assessment page of a
failed assessment shows the reason. The [API Reference](api.md#uploads)
describes how to list older uploads.

The collection time comes from the name that radar gives the archive, so a
renamed archive has no collection time.

![The console's front page: the upload bar, and the list of assessments with each host, its collection time, and its verdict](img/console-front-page-light.jpg#only-light)
![The console's front page: the upload bar, and the list of assessments with each host, its collection time, and its verdict](img/console-front-page-dark.jpg#only-dark)

## Assessing an Upload Again

The analyst keeps every uploaded archive, so you can assess an upload again at
any time. To redo an assessment from the stored archive, open the assessment,
select **Assess again**, and confirm. The new result replaces the previous
result. Assessing again is useful after you configure a provider, or after a
stop interrupts an assessment.

## Deleting an Assessment

Each entry in the console's list of assessments has a delete button. The button
asks for confirmation and then for the admin token. The console remembers the
token until you close the browser tab. Deleting an assessment also deletes the
uploaded archive.

The analyst generates the admin token on first start and stores the token in
the `archives` volume. The following command prints the admin token:

```bash
docker compose exec app cat /data/admin-token
```

To choose the token yourself, set `RADAR_ANALYST_ADMIN_TOKEN` in `.env` and run
`docker compose up -d --wait` again. The analyst then accepts only that token
and ignores the token in `/data/admin-token`.

## Using the API

The console reads everything that it displays from a JSON API, and any other
client can use the same endpoints. The [API Reference](api.md) describes each
endpoint, and the [API Browser](api/browser.md) renders the OpenAPI description
of the API. A running analyst also serves an interactive browser at
[http://localhost:8080/docs](http://localhost:8080/docs).

## Next Steps

The following documents describe related tasks:

- The [Managing an Installation](managing.md) document describes the volumes,
  the logs, backups, and upgrades.
- The [API Reference](api.md) document describes the JSON API that the console
  and any other client use.
- The [Troubleshooting](troubleshooting.md) document describes common problems
  and how to solve each one.
