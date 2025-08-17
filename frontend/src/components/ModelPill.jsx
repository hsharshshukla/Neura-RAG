// src/components/ModelPill.jsx
const MODEL_BY_TIER = {
    free: "GPT-4o mini",
    mini: "GPT-4o mini",
    pro: "GPT-4o",
  };
  
  export default function ModelPill({ tier }) {
    const name = MODEL_BY_TIER[(tier || "free").toLowerCase()] || "GPT-4o mini";
    return (
      <span className="text-[10px] px-2 py-0.5 rounded border bg-indigo-50 text-indigo-700 border-indigo-200" title="Model for your plan">
        {name}
      </span>
    );
  }
  