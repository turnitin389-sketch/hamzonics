"use client";

import { cloneElement, isValidElement, useId } from "react";

/** Label + control, linked with htmlFor/id so screen readers and click-to-focus work. */
export function Field({ label, children, className }: { label: string; children: React.ReactElement<{ id?: string }>; className?: string }) {
  const id = useId();
  const control = isValidElement(children) ? cloneElement(children, { id: children.props.id ?? id }) : children;
  return (
    <div className={className}>
      <label className="label" htmlFor={children.props.id ?? id}>{label}</label>
      {control}
    </div>
  );
}
