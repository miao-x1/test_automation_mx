/**
 * Web - 定时任务
 *
 * 复用 SchedulePage + ScheduleHistoryPage
 */
import SchedulePage from '../SchedulePage';
import { ClockCircleOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';

export default function WebSchedule() {
  return (
    <div>
      <PageHeader title="定时任务" subtitle="管理Web测试的定时调度" icon={<ClockCircleOutlined />} />
      <SchedulePage />
    </div>
  );
}
