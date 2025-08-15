export default function Card({ title, action, children }) {
    return (
      <section className="bg-white rounded-2xl p-4 border border-gray-200 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold">{title}</h3>
          {action}
        </div>
        {children}
      </section>
    );
  }