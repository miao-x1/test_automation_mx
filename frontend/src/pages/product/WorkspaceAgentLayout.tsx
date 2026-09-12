import type { ReactNode } from 'react';
import ProjectAgentPanel from './ProjectAgentPanel';

export default function WorkspaceAgentLayout({
  workspace,
  testTaskId,
  children,
}: {
  workspace: 'understand' | 'design' | 'execute';
  testTaskId?: number;
  children: ReactNode;
}) {
  return (
    <div className="project-agent-layout">
      <div className="project-agent-main">{children}</div>
      <ProjectAgentPanel workspace={workspace} testTaskId={testTaskId} />
    </div>
  );
}
