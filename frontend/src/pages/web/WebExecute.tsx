/**
 * Web - 执行中心
 *
 * 展示任务列表，点击可进入任务详情执行
 * 复用 TaskCenter 组件
 */
import TaskCenter from '../TaskCenter';
import { PlayCircleOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';

export default function WebExecute() {
  return (
    <div>
      <PageHeader title="执行中心" subtitle="选择任务并执行" icon={<PlayCircleOutlined />} />
      <TaskCenter />
    </div>
  );
}
