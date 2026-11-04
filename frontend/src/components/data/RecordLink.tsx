import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

/** Your Data, showing just this record with its details open (Back returns to where the link was). */
export const dataRecordPath = (object: string, id: string) =>
  `/data/${encodeURIComponent(object)}?only=${encodeURIComponent(id)}&record=${encodeURIComponent(id)}`;

/** A record's name in a table: opens the record in Your Data. The row's own icon still opens it in Salesforce. */
export function RecordLink({ object, id, from = 'opened from a health check table', children }: {
  object: string;
  id: string;
  /** Shown on the Your Data banner: where the record was opened from. */
  from?: string;
  children: ReactNode;
}) {
  return (
    <Link to={dataRecordPath(object, id)} state={{ from }} title="Open this record in Your Data" className="font-medium text-ink hover:text-brand hover:underline">
      {children}
    </Link>
  );
}
