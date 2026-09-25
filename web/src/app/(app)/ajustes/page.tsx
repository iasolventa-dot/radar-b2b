import { Settings } from "lucide-react";
import { AjustesApify } from "@/components/ajustes-apify";
import { EncabezadoPagina } from "@/components/encabezado-pagina";
import { AjustesPlaces } from "@/components/ajustes-places";

export const dynamic = "force-dynamic";

export default function PaginaAjustes() {
  return (
    <div className="entrada space-y-6">
      <EncabezadoPagina icono={Settings} antetitulo="Configuración" titulo="Ajustes">
        <p>
          Fuentes de datos que necesitan una clave. Las fuentes gratuitas (BORME, PLACSP, OpenStreetMap, INE,
          CartoCiudad y búsqueda web) no requieren nada aquí.
        </p>
      </EncabezadoPagina>
      <AjustesPlaces />
      <AjustesApify />
    </div>
  );
}
