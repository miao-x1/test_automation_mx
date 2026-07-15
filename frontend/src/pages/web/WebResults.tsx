/**
 * Web - 报告中心
 *
 * 展示所有执行记录（含缺陷分析）
 * 复用 ExecutionCenter 组件
 */
import ExecutionCenter from '../ExecutionCenter';
import { BarChartOutlined } from '@ant-design/icons';
import { PageHeader } from '../../components/UI';

export default function WebResults() {
  return (
    <div>
      <PageHeader title="报告中心" subtitle="查看所有执行记录和缺陷分析" icon={<BarChartOutlined />} />
      <ExecutionCenter />
    </div>
  );
}
