import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Select, message } from 'antd';
import { fetchWorkspace, type Project } from '@/services/workspace';
import { getCurrentProjectId, setCurrentProjectId, PROJECT_CHANGED } from './projectStore';

function isProjectWorkPage(pathname: string): boolean {
  return (
    pathname === '/' ||
    pathname === '/home' ||
    pathname === '/dashboard' ||
    pathname.startsWith('/task') ||
    pathname.startsWith('/execution') ||
    pathname.startsWith('/report') ||
    pathname.startsWith('/asset') ||
    pathname.startsWith('/performance')
  );
}

export default function ProjectSwitcher() {
  const navigate = useNavigate();
  const location = useLocation();
  const [projects, setProjects] = useState<Project[]>([]);
  const [value, setValue] = useState<number | undefined>(getCurrentProjectId() || undefined);

  useEffect(() => {
    fetchWorkspace().then((data) => {
      const items: Project[] = data?.projects || [];
      setProjects(items);
      const current = getCurrentProjectId();
      const fallback = items.find((item) => item.id === (data?.default_project_id || items[0]?.id));
      const labelOf = (project?: Project) => (
        project?.organization_name ? `${project.name} · ${project.organization_name}` : (project?.name || '')
      );
      if (!current && fallback) {
        setCurrentProjectId(fallback.id, labelOf(fallback));
        setValue(fallback.id);
      } else if (current) {
        const named = items.find((item) => item.id === current);
        if (named) setCurrentProjectId(named.id, labelOf(named));
        setValue(current);
      }
    }).catch(() => {
      /* keep header usable */
    });
  }, []);

  useEffect(() => {
    const sync = () => setValue(getCurrentProjectId() || undefined);
    window.addEventListener(PROJECT_CHANGED, sync);
    return () => window.removeEventListener(PROJECT_CHANGED, sync);
  }, []);

  if (!projects.length) return null;

  return (
    <div className="product-switcher">
      <span>当前项目</span>
      <Select
        value={value}
        style={{ minWidth: 160 }}
        options={projects.map((project) => ({
          value: project.id,
          label: project.organization_name ? `${project.name} · ${project.organization_name}` : project.name,
        }))}
        onChange={(id) => {
          const project = projects.find((item) => item.id === id);
          const label = project?.organization_name
            ? `${project.name} · ${project.organization_name}`
            : (project?.name || String(id));
          setValue(id);
          setCurrentProjectId(id, label);
          message.success(`已切换到「${label}」，任务和报告都只看这个项目`);
          if (location.pathname.startsWith('/workspace/project/')) {
            navigate(`/workspace/project/${id}`);
            return;
          }
          if (!isProjectWorkPage(location.pathname)) {
            navigate('/task/create');
          }
        }}
      />
    </div>
  );
}
