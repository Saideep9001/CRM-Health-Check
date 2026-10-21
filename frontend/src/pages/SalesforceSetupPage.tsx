import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { SalesforceAppSetup } from '@/components/connection/SalesforceAppSetup';
import { PageHeader } from '@/components/ui/Page';

/** One-time Connected App setup, opened from Connect Salesforce. */
export default function SalesforceSetupPage() {
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);

  return (
    <div>
      <Link to="/connection" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Back to Connect Salesforce
      </Link>
      <PageHeader title="Salesforce app setup" description="A one-time step before anyone can connect Salesforce." />
      <SalesforceAppSetup editing={editing} onEditingChange={setEditing} onSaved={() => navigate('/connection?connect=1')} />
    </div>
  );
}
