/**
 * 需求模块 - 需求拆解
 *
 * 将复杂需求拆解为多个子任务
 * 输入层：只拆解，不执行
 */
import { useState } from 'react';
import { Card, Input, Button, List, Tag, Space, message, Empty } from 'antd';
import { ScissorOutlined, PlusOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import request from '../../services/request';

interface SubTask {
  id: string;
  name: string;
  description: string;
  priority: 'high' | 'medium' | 'low';
  type: string;
}

export default function RequirementDecompose() {
  const [requirement, setRequirement] = useState('');
  const [subTasks, setSubTasks] = useState<SubTask[]>([]);
  const [loading, setLoading] = useState(false);

  const handleDecompose = async () => {
    if (!requirement.trim()) {
      message.warning('请输入需求内容');
      return;
    }
    setLoading(true);
    try {
      // 调用后端需求创建接口
      const res: any = await request.post('/requirement/create', {
        requirement: requirement.trim(),
        input_mode: 'text',
      });
      if (res.code === 200 && res.data) {
        const taskId = res.data.task_id || res.data.id;
        if (taskId) {
          // 调用分析接口
          const analyzeRes: any = await request.post(`/requirement/analyze/${taskId}`);
          if (analyzeRes.code === 200 && analyzeRes.data) {
            const steps = analyzeRes.data.steps || analyzeRes.data.test_steps || [];
            setSubTasks(
              steps.length > 0
                ? steps.map((step: any, index: number) => ({
                    id: step.id ? String(step.id) : String(index + 1),
                    name: step.name || step.title || `步骤 ${index + 1}`,
                    description: step.description || step.desc || '',
                    priority: step.priority || 'medium',
                    type: step.type || 'web',
                  }))
                : [
                    { id: '1', name: '需求已提交', description: `任务ID: ${taskId}，正在分析中...`, priority: 'medium', type: 'web' },
                  ],
            );
          } else {
            setSubTasks([
              { id: '1', name: '需求已提交', description: `任务ID: ${taskId}`, priority: 'medium', type: 'web' },
            ]);
          }
          message.success('需求拆解完成');
        } else {
          message.warning('需求已提交，但未获取到任务ID');
        }
      } else {
        message.error(res.message || '需求分析失败');
      }
    } catch (err) {
      message.error('需求分析请求失败');
    } finally {
      setLoading(false);
    }
  };

  const priorityColor = { high: 'red', medium: 'orange', low: 'blue' };

  return (
    <div>
      <PageHeader title="需求拆解" subtitle="将复杂需求拆解为可执行的子任务" icon={<ScissorOutlined />} />
      <Card>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <div>
            <Input.TextArea
              value={requirement}
              onChange={e => setRequirement(e.target.value)}
              placeholder="输入需求内容，AI将自动拆解为子任务..."
              rows={4}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={handleDecompose} loading={loading} style={{ marginTop: 8 }}>
              开始拆解
            </Button>
          </div>
          {subTasks.length > 0 ? (
            <List
              dataSource={subTasks}
              renderItem={(item) => (
                <List.Item extra={<Tag color={priorityColor[item.priority]}>{item.priority}</Tag>}>
                  <List.Item.Meta title={item.name} description={item.description} />
                </List.Item>
              )}
            />
          ) : (
            <Empty description="输入需求后点击拆解" />
          )}
        </Space>
      </Card>
    </div>
  );
}
