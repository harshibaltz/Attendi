import React from 'react';
import { MessageCircle } from 'lucide-react';
import { SectionHeader } from '../../components/UI';
import { SupportMessagesPanel } from '../Settings/Settings';

const AdminSupportMessages = () => {
  return (
    <div className="space-y-5">
      <SectionHeader
        area="hub"
        icon={MessageCircle}
        title="Customer Messages"
        subtitle="Messages submitted from Settings > Customer Care"
      />
      <SupportMessagesPanel />
    </div>
  );
};

export default AdminSupportMessages;
