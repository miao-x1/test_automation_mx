/**
 * 需求模块 - 需求转测试任务
 *
 * 将AI分析完成的需求转为测试任务（Task），跳转到Web执行层
 * 输入层：只生成Task，不执行。执行由Web模块负责
 */
import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Card, Descriptions, Button, Space, Tag, Result, Spin } from 'antd';
import { ArrowRightOutlined, CheckCircleOutlined, RocketOutlined } from '@ant-design/icons';
import request from '../../services/request';
import { PageHeader } from '../../components/UI';

interface TaskInfo {
  id: number;
  task_name: string;
  task_type: string;
  status: string;
  script_content?: string;
  created_at: string;
}

export default function RequirementToTask() {
  const navigate = useNavigate();
  const { taskId } = useParams();
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) {
      setError('缺少任务ID');
      setLoading(false);
      return;
    }
    const fetchTask = async () => {
      try {
        const res: any = await request.get(`/tasks/${taskId}`);
        setTask(res?.data || res);
      } catch (e: any) {
        console.error('[RequirementToTask] fetch failed:', e);
        setError(e?.message || '加载任务失败');
      } finally {
        setLoading(false);
      }
    };
    fetchTask();
  }, [taskId]);

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>;

  if (error) {
    return (
      <Card>
        <Result status="error" title="加载失败" subTitle={error}
          extra={<Button onClick={() => navigate('/requirement')}>返回需求列表</Button>}
        />
      </Card>
    );
  }

  return (
    <div>
      <PageHeader title="需求转测试任务" subtitle="确认任务信息，前往Web执行层执行测试" icon={<RocketOutlined />} />
      <Card>
        {task ? (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Descriptions bordered column={1}>
              <Descriptions.Item label="任务ID">{task.id}</Descriptions.Item>
              <Descriptions.Item label="任务名称">{task.task_name}</Descriptions.Item>
              <Descriptions.Item label="任务类型"><Tag color="blue">{task.task_type}</Tag></Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={task.status === 'pending' ? 'orange' : 'green'}>{task.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="创建时间">{task.created_at}</Descriptions.Item>
            </Descriptions>

            <Result
              icon={<CheckCircleOutlined />}
              title="需求已转为测试任务"
              subTitle="需求模块的工作已完成。执行测试请前往 Web 执行层"
              extra={[
                <Button key="list" onClick={() => navigate('/requirement')}>返回需求列表</Button>,
                <Button key="execute" type="primary" icon={<ArrowRightOutlined />}
                  onClick={() => navigate(`/web/task/${task.id}`)}>
                  前往执行测试
                </Button>,
              ]}
            />
          </Space>
        ) : (
          <Result status="warning" title="任务不存在"
            extra={<Button onClick={() => navigate('/requirement')}>返回需求列表</Button>}
          />
        )}
      </Card>
    </div>
  );
}
