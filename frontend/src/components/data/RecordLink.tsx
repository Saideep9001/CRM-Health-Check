import type { MouseEvent, ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';

const FROM = 'opened from a health check table';

/** Your Data, showing just this record with its details open (Back returns to where the link was). */
export const dataRecordPath = (object: string, id: string) =>
  `/data/${encodeURIComponent(object)}?only=${encodeURIComponent(id)}&record=${encodeURIComponent(id)}`;

/** A record's name in a table: opens the record in Your Data. The row's own icon still opens it in Salesforce. */
export function RecordLink({ object, id, from = FROM, children }: {
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

/** A click anywhere on a table row opens its record in Your Data, except on the row's own links and buttons (the
 *  Salesforce icon, a filter) or when text is being selected. Returns nothing for a row with no record id. */
export function useOpenRecord(from = FROM) {
  const navigate = useNavigate();
  return (object: string, id: string | null | undefined) =>
    id
      ? {
          onClick: (e: MouseEvent<HTMLElement>) => {
            if ((e.target as HTMLElement).closest('a, button, input, select, label, [role="button"]')) return;
            if (window.getSelection()?.toString()) return;
            navigate(dataRecordPath(object, id), { state: { from } });
          },
          className: 'cursor-pointer',
        }
      : { onClick: undefined, className: '' };
}
