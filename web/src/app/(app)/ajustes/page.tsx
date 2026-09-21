import { AjustesApify } from "@/components/ajustes-apify";
import { AjustesPlaces } from "@/components/ajustes-places";

export const dynamic = "force-dynamic";

export default function PaginaAjustes() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Ajustes</h1>
        <p className="mt-1 text-sm text-slate-500">
          Fuentes de datos que necesitan una clave. Las fuentes gratuitas (BORME, PLACSP, OpenStreetMap, INE,
          CartoCiudad y búsqueda web) no requieren nada aquí.
        </p>
      </div>
      <AjustesPlaces />
      <AjustesApify />
    </div>
  );
}
