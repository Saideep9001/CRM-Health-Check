import { Compass } from 'lucide-react';
import { LinkButton } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/States';

export default function NotFoundPage() {
  return (
    <div className="card">
      <EmptyState
        icon={<Compass className="h-6 w-6" />}
        title="Page not found"
        description="We couldn’t find that page."
        action={
          <LinkButton to="/dashboard" variant="primary" size="sm">
            Back to overview
          </LinkButton>
        }
      />
    </div>
  );
}
