# Pilot intake operations

The public intake stores name, work email, organization, GPU environment, goal, and creation time in D1 table `pilot_requests`. Treat the table as confidential lead data. Never commit exports to source control.

## Monthly retention review

Run this against the production D1 database at least monthly, and record the date and affected-row count in the operating log:

```sql
DELETE FROM pilot_requests
WHERE datetime(created_at) < datetime('now', '-90 days');
```

The application also attempts this cleanup before each successful insert, but that does not replace the monthly review because a quiet intake may receive no new inserts.

## Deletion request

After verifying that the requester controls the email address used in the submission, preview the target:

```sql
SELECT id, email, created_at
FROM pilot_requests
WHERE lower(email) = lower(?);
```

Delete only the verified address:

```sql
DELETE FROM pilot_requests
WHERE lower(email) = lower(?);
```

## Synthetic QA cleanup

QA submissions must use `@example.invalid` and include `SYNTHETIC QA` in the organization or goal. Preview before deleting:

```sql
SELECT id, email, organization, created_at
FROM pilot_requests
WHERE email LIKE '%@example.invalid';
```

Then remove only reviewed synthetic rows:

```sql
DELETE FROM pilot_requests
WHERE email LIKE '%@example.invalid';
```

## Lead handling

- Review new requests at least each business day.
- Do not copy credentials, IP addresses, or secrets into notes.
- Reply only through the configured `pilot@gridrudder.com` mailbox.
- Record qualification outcome without exporting full submissions unless necessary.
