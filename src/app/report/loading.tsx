import { ReportPendingState } from "@/components/report/report-pending-state";
import { Card } from "@/components/ui/card";

export default function ReportLoading() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl items-center justify-center px-6 py-10 md:px-10">
      <Card className="px-6 py-5">
        <ReportPendingState
          label="AI 分析中..."
          detail="报告页已打开，正在补全内容。"
        />
      </Card>
    </main>
  );
}
