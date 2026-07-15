/**
 * Web - 定时任务历史记录
 *
 * 复用 ScheduleHistoryPage
 */
import ScheduleHistoryPage from '../ScheduleHistoryPage';
import { HistoryOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';

export default function WebScheduleHistory() {
  return (
    <div>
      <PageHeader title="历史记录" subtitle="定时任务执行历史" icon={<HistoryOutlined />} />
      <ScheduleHistoryPage />
    </div>
  );
}
