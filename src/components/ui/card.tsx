import clsx from "clsx";
import type { HTMLAttributes } from "react";

export function Card({ children, className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx(
        "rounded-3xl border border-white/10 bg-white shadow-[0_12px_40px_rgba(15,23,42,0.08)]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
