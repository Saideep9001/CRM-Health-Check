import { useMemo, useState } from 'react';

export type SortDir = 'asc' | 'desc';

export function useSort<T, K extends string>(
  rows: T[],
  initialKey: K,
  getValue: (row: T, key: K) => string | number | null,
  initialDir: SortDir = 'desc',
) {
  const [key, setKey] = useState<K>(initialKey);
  const [dir, setDir] = useState<SortDir>(initialDir);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const va = getValue(a, key);
      const vb = getValue(b, key);
      if (va === vb) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      const cmp =
        typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb));
      return dir === 'asc' ? cmp : -cmp;
    });
    return copy;
  }, [rows, key, dir]);

  const toggle = (k: K) => {
    if (k === key) setDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setKey(k);
      setDir('desc');
    }
  };

  return { sorted, sortKey: key, sortDir: dir, toggle };
}
