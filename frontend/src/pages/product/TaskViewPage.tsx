import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Spin, message } from 'antd';
import request from '@/services/request';
import { extractPageUrl, parseCases, unwrap } from './helpers';
import TestResultView from './TestResultView';
import './product.css';

export default function TaskViewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [task, setTask] = useState<any>(null);
  const [execution, setExecution] = useState<any>(null);

  useEffect(() => {
    const load = async () => {
      if (!id) return;
      setLoading(true);
      try {
        const res: any = await request.get(`/requirement/${id}`);
        const detail = unwrap(res);
        setTask(detail);
        if (detail?.task_id) {
          const listRes: any = await request.get(`/executions/task/${detail.task_id}/list`);
          const items = unwrap(listRes)?.items || unwrap(listRes) || [];
          const latest = Array.isArray(items) ? items[0] : null;
          if (latest?.id) {
            const execRes: any = await request.get(`/executions/${latest.id}`);
            setExecution(unwrap(execRes));
          } else if (detail.execution_id) {
            const execRes: any = await request.get(`/executions/${detail.execution_id}`);
            setExecution(unwrap(execRes));
          }
        }
      } catch {
        message.error('无法加载测试任务');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 80 }}><Spin /></div>;
  }

  if (!task) {
    return (
      <div className="product-shell">
        <div className="product-card">未找到这个测试任务。</div>
      </div>
    );
  }

  return (
    <div className="product-shell">
      <div className="product-hero">
        <h1>测试任务</h1>
        <p>{extractPageUrl(task.requirement) || task.requirement}</p>
      </div>
      {execution ? (
        <TestResultView
          result={execution}
          cases={parseCases(task.generated_case)}
          executionId={execution.id}
          onRetest={() => navigate(`/test?rerun=${id}`)}
          onBack={() => navigate('/assets?tab=tasks')}
        />
      ) : (
        <div className="product-card">
          <p>这个任务还没有执行结果。</p>
          <p className="product-note">已生成步骤：{parseCases(task.generated_case).length} 条</p>
          <Button type="primary" onClick={() => navigate(`/test?rerun=${id}`)}>重新测试</Button>
        </div>
      )}
    </div>
  );
}
