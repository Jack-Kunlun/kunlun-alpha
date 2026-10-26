import { useRef, useState } from "react";
import { DetailDrawer } from "@/components/detail-drawer";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { MarketQualityEvidenceDetail, MarketQualityEvidencePage } from "@kunlun/shared-types";
import type { ObjectQueryResult } from "@/lib/use-api-query";
import { formatShanghaiTime } from "./format-shanghai-time";
import { useMarketQualityEvidenceDetail } from "./use-market-quality-evidence";

const DETAIL_PAGE_SIZE = 50;

function shortOpaqueId(value: string): string {
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

interface MarketQualityEvidencePanelProps {
  result: ObjectQueryResult<MarketQualityEvidencePage>;
  onPrevious: () => void;
  onNext: () => void;
}

function ArrayPager({
  label,
  page,
  pageCount,
  onPrevious,
  onNext,
}: {
  label: string;
  page: number;
  pageCount: number;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (pageCount <= 1) return null;
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span>
        {label}：第 {page + 1}/{pageCount} 页
      </span>
      <Button type="button" variant="outline" size="sm" onClick={onPrevious} disabled={page === 0}>
        上一页
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onNext}
        disabled={page >= pageCount - 1}
      >
        下一页
      </Button>
    </div>
  );
}

function EvidenceDetail({ detail }: { detail: MarketQualityEvidenceDetail }) {
  const [eventPage, setEventPage] = useState(0);
  const [filteredPage, setFilteredPage] = useState(0);
  const eventPageCount = Math.max(
    1,
    Math.ceil(detail.record.qualityEvents.length / DETAIL_PAGE_SIZE),
  );
  const filteredPageCount = Math.max(
    1,
    Math.ceil(detail.record.filteredRecords.length / DETAIL_PAGE_SIZE),
  );
  const events = detail.record.qualityEvents.slice(
    eventPage * DETAIL_PAGE_SIZE,
    (eventPage + 1) * DETAIL_PAGE_SIZE,
  );
  const filteredRecords = detail.record.filteredRecords.slice(
    filteredPage * DETAIL_PAGE_SIZE,
    (filteredPage + 1) * DETAIL_PAGE_SIZE,
  );

  return (
    <div className="space-y-3 rounded-md border p-3" aria-label="行情质量证据明细">
      <div className="grid gap-2 text-sm md:grid-cols-2">
        <p className="min-w-0">
          证据 ID：
          <span className="break-all" title={detail.record.evidenceId}>
            {shortOpaqueId(detail.record.evidenceId)}
          </span>
        </p>
        <p>来源：{detail.record.source}</p>
        <p>证券：{detail.record.unifiedCode}</p>
        <p>周期：{detail.record.interval}</p>
        <p>状态：{detail.record.status}</p>
        <p>原因：{detail.record.reasonCode}</p>
        <p>
          请求窗口：{detail.record.requestedStart} 至 {detail.record.requestedEnd}
        </p>
        <p>捕获可用：{formatShanghaiTime(detail.record.captureAvailableAt)}</p>
        <p>证据记录：{formatShanghaiTime(detail.record.qualityRecordedAt)}</p>
        <p>拒绝记录数：{detail.record.rejectedRecordCount}</p>
        <p>质量事件数：{detail.record.qualityEventCount}</p>
        <p>过滤记录数：{detail.record.filteredRecordCount}</p>
      </div>
      {detail.record.qualityEvents.length > 0 && (
        <div className="space-y-2">
          <h5 className="font-medium">质量事件</h5>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {events.map((event, index) => (
              <li key={`${event.kind}-${event.timestamp ?? "none"}-${index}`}>
                {event.kind} · {event.unifiedCode ?? "未能安全解析证券"} ·{" "}
                {event.timestamp === null
                  ? "时间未能安全解析"
                  : formatShanghaiTime(event.timestamp)}
              </li>
            ))}
          </ul>
          <ArrayPager
            label="质量事件"
            page={eventPage}
            pageCount={eventPageCount}
            onPrevious={() => setEventPage((value) => Math.max(0, value - 1))}
            onNext={() => setEventPage((value) => Math.min(eventPageCount - 1, value + 1))}
          />
        </div>
      )}
      {detail.record.filteredRecords.length > 0 && (
        <div className="space-y-2">
          <h5 className="font-medium">过滤记录</h5>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {filteredRecords.map((record) => (
              <li key={`${record.rawRowIndex}-${record.timestamp}`}>
                原始行 {record.rawRowIndex} · {formatShanghaiTime(record.timestamp)} ·{" "}
                {record.reasonCode}
              </li>
            ))}
          </ul>
          <ArrayPager
            label="过滤记录"
            page={filteredPage}
            pageCount={filteredPageCount}
            onPrevious={() => setFilteredPage((value) => Math.max(0, value - 1))}
            onNext={() => setFilteredPage((value) => Math.min(filteredPageCount - 1, value + 1))}
          />
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        公开证据快照发布时间：{formatShanghaiTime(detail.publishedAt)}。此明细不包含原始行情、原始
        capture、校验和、路径或自由文本。
      </p>
    </div>
  );
}

export function MarketQualityEvidencePanel({
  result,
  onPrevious,
  onNext,
}: MarketQualityEvidencePanelProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const page = result.data;
  const selectedRecord =
    selectedId === null
      ? undefined
      : page?.records.find((record) => record.evidenceId === selectedId);
  const activeSelectedId = selectedRecord?.evidenceId ?? null;
  const detailResult = useMarketQualityEvidenceDetail(activeSelectedId, page?.snapshotId ?? null);

  if (result.status === "loading") {
    return (
      <p role="status" className="text-muted-foreground">
        行情质量证据加载中…
      </p>
    );
  }
  if (result.status === "forbidden") {
    return (
      <p role="alert" className="text-destructive">
        无权访问行情质量证据
      </p>
    );
  }
  if (result.status === "error" || page === null) {
    return (
      <p role="alert" className="text-destructive">
        行情质量证据暂不可用：可能尚未发布或读取失败，不代表无异常。请稍后重试
      </p>
    );
  }
  if (page.snapshotRecordCount === 0) {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground">当前公开快照没有行情质量证据记录。</p>
        <p className="text-xs text-muted-foreground">
          这不表示行情没有质量问题，也不表示全市场覆盖完整。快照发布时间：
          {formatShanghaiTime(page.publishedAt)}。
        </p>
      </div>
    );
  }
  if (page.matchingRecordCount === 0) {
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground">当前筛选条件下暂无行情质量证据记录。</p>
        <p className="text-xs text-muted-foreground">
          日期筛选按证据请求窗口与输入日期范围是否相交判断；快照发布时间：
          {formatShanghaiTime(page.publishedAt)}。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        固定快照：
        <span className="break-all" title={page.snapshotId}>
          {shortOpaqueId(page.snapshotId)}
        </span>{" "}
        · 发布：{formatShanghaiTime(page.publishedAt)} · 当前显示 {page.records.length}/{" "}
        {page.matchingRecordCount} 条
      </p>
      <div className="overflow-x-auto">
        <Table aria-label="行情质量证据列表" className="min-w-[1200px]">
          <TableHeader>
            <TableRow>
              <TableHead>证券</TableHead>
              <TableHead>来源</TableHead>
              <TableHead>周期</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>原因</TableHead>
              <TableHead>请求窗口</TableHead>
              <TableHead>证据记录时间（上海）</TableHead>
              <TableHead>计数</TableHead>
              <TableHead className="sticky right-0 z-10 w-28 bg-background shadow-[-1px_0_0_var(--border)]">
                操作
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.records.map((record) => (
              <TableRow key={record.evidenceId}>
                <TableCell>{record.unifiedCode}</TableCell>
                <TableCell>{record.source}</TableCell>
                <TableCell>{record.interval}</TableCell>
                <TableCell>{record.status}</TableCell>
                <TableCell>{record.reasonCode}</TableCell>
                <TableCell>
                  {record.requestedStart} 至 {record.requestedEnd}
                </TableCell>
                <TableCell>{formatShanghaiTime(record.qualityRecordedAt)}</TableCell>
                <TableCell>
                  拒绝 {record.rejectedRecordCount} / 事件 {record.qualityEventCount} / 过滤{" "}
                  {record.filteredRecordCount}
                </TableCell>
                <TableCell className="sticky right-0 z-10 w-28 bg-background shadow-[-1px_0_0_var(--border)]">
                  <Button
                    type="button"
                    variant="link"
                    size="sm"
                    aria-label={`查看详情 ${record.unifiedCode} ${record.source}`}
                    aria-haspopup="dialog"
                    onClick={(event) => {
                      triggerRef.current = event.currentTarget;
                      setSelectedId(record.evidenceId);
                    }}
                  >
                    查看详情
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Button type="button" variant="outline" onClick={onPrevious} disabled={page.offset === 0}>
          上一页
        </Button>
        <Button type="button" variant="outline" onClick={onNext} disabled={!page.hasMore}>
          下一页
        </Button>
        <span>固定快照分页，不会跨发布版本。</span>
      </div>
      <DetailDrawer
        open={activeSelectedId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedId(null);
        }}
        title="行情质量证据详情"
        description={
          selectedRecord === undefined
            ? "查看已发布的脱敏证据。"
            : `${selectedRecord.unifiedCode} · ${selectedRecord.source} · ${selectedRecord.status}。固定公开快照，不代表当前行情健康状态。`
        }
        returnFocusRef={triggerRef}
      >
        {activeSelectedId !== null && detailResult.status === "loading" && (
          <p role="status" className="text-muted-foreground">
            证据明细加载中…
          </p>
        )}
        {activeSelectedId !== null && detailResult.status === "forbidden" && (
          <p role="alert" className="text-destructive">
            无权访问行情质量证据明细
          </p>
        )}
        {activeSelectedId !== null &&
          (detailResult.status === "error" || detailResult.status === "empty") && (
            <p role="alert" className="text-destructive">
              行情质量证据明细暂不可用：可能尚未发布或读取失败，不代表无异常
            </p>
          )}
        {activeSelectedId !== null &&
          detailResult.status === "success" &&
          detailResult.data !== null && (
            <EvidenceDetail key={activeSelectedId} detail={detailResult.data} />
          )}
      </DetailDrawer>
    </div>
  );
}
