# src/core/context_builder.py
# -*- coding: utf-8 -*-

"""
Módulo para Construcción de Contexto Base de Parlamentarios v1.0

Este script genera un contexto completo y estructurado para un parlamentario específico,
reuniendo información de todas las tablas relacionadas en la base de datos.
El contexto generado sirve como base para el sistema RAG del chatbot.
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any

# --- CONFIGURACIÓN ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')


class ParlamentarioContextBuilder:
    """
    Clase para construir el contexto completo de un parlamentario
    desde todas las fuentes de la base de datos.
    """
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
    
    def __enter__(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Para acceder a columnas por nombre
        self.cursor = self.conn.cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()
    
    def _dict_from_row(self, row) -> Dict:
        """Convierte una fila de SQLite en diccionario."""
        if row is None:
            return {}
        return {key: row[key] for key in row.keys()}
    
    def get_perfil_basico(self, mp_uid: int) -> Dict:
        """Obtiene el perfil biográfico básico del parlamentario."""
        query = """
            SELECT 
                mp_uid,
                nombre_completo,
                nombre_propio,
                apellido_paterno,
                apellido_materno,
                genero,
                fecha_nacimiento,
                lugar_nacimiento,
                diputadoid,
                bcn_uri,
                url_foto,
                twitter_handle,
                sitio_web_personal,
                profesion,
                url_historia_politica,
                fecha_extraccion,
                -- Calcular edad si hay fecha de nacimiento
                CASE 
                    WHEN fecha_nacimiento IS NOT NULL 
                    THEN CAST((julianday('now') - julianday(fecha_nacimiento)) / 365.25 AS INTEGER)
                    ELSE NULL 
                END as edad
            FROM dim_parlamentario
            WHERE mp_uid = ?
        """
        self.cursor.execute(query, (mp_uid,))
        return self._dict_from_row(self.cursor.fetchone())
    
    def get_mandatos_historicos(self, mp_uid: int) -> List[Dict]:
        """Obtiene el historial de mandatos parlamentarios."""
        query = """
            SELECT 
                mandato_id,
                cargo,
                distrito,
                fecha_inicio,
                fecha_fin,
                CASE 
                    WHEN fecha_fin IS NULL OR fecha_fin >= date('now') 
                    THEN 'Activo'
                    ELSE 'Finalizado'
                END as estado_mandato,
                -- Calcular duración en días
                CASE 
                    WHEN fecha_fin IS NOT NULL 
                    THEN julianday(fecha_fin) - julianday(fecha_inicio)
                    ELSE julianday('now') - julianday(fecha_inicio)
                END as duracion_dias
            FROM parlamentario_mandatos
            WHERE mp_uid = ?
            ORDER BY fecha_inicio DESC
        """
        self.cursor.execute(query, (mp_uid,))
        return [self._dict_from_row(row) for row in self.cursor.fetchall()]
    
    def get_militancia_historica(self, mp_uid: int) -> List[Dict]:
        """Obtiene el historial completo de militancias partidarias."""
        query = """
            SELECT 
                mh.militancia_id,
                p.nombre_partido,
                p.sigla,
                p.url_historia_politica as url_partido,
                mh.fecha_inicio,
                mh.fecha_fin,
                CASE 
                    WHEN mh.fecha_fin IS NULL OR mh.fecha_fin >= date('now') 
                    THEN 'Actual'
                    ELSE 'Anterior'
                END as estado_militancia
            FROM militancia_historial mh
            JOIN dim_partidos p ON mh.partido_id = p.partido_id
            WHERE mh.mp_uid = ?
            ORDER BY mh.fecha_inicio DESC
        """
        self.cursor.execute(query, (mp_uid,))
        return [self._dict_from_row(row) for row in self.cursor.fetchall()]
    
    def get_comisiones(self, mp_uid: int) -> List[Dict]:
        """Obtiene las comisiones en las que participa o participó."""
        query = """
            SELECT 
                c.nombre_comision,
                c.tipo as tipo_comision,
                cm.rol,
                cm.fecha_inicio,
                cm.fecha_fin,
                CASE 
                    WHEN cm.fecha_fin IS NULL OR cm.fecha_fin >= date('now') 
                    THEN 'Activo'
                    ELSE 'Inactivo'
                END as estado_membresia
            FROM comision_membresias cm
            JOIN dim_comisiones c ON cm.comision_id = c.comision_id
            WHERE cm.mp_uid = ?
            ORDER BY cm.fecha_inicio DESC
        """
        self.cursor.execute(query, (mp_uid,))
        return [self._dict_from_row(row) for row in self.cursor.fetchall()]
    
    def get_proyectos_autor(self, mp_uid: int) -> List[Dict]:
        """Obtiene los proyectos de ley donde es autor/coautor."""
        query = """
            SELECT 
                b.bill_id,
                b.titulo,
                b.resumen,
                b.fecha_ingreso,
                b.etapa,
                b.iniciativa,
                b.origen,
                b.urgencia,
                b.resultado_final,
                b.ley_numero,
                b.ley_fecha_publicacion,
                -- Contar coautores
                (SELECT COUNT(*) - 1 FROM bill_authors WHERE bill_id = b.bill_id) as num_coautores
            FROM bills b
            JOIN bill_authors ba ON b.bill_id = ba.bill_id
            WHERE ba.mp_uid = ?
            ORDER BY b.fecha_ingreso DESC
        """
        self.cursor.execute(query, (mp_uid,))
        return [self._dict_from_row(row) for row in self.cursor.fetchall()]
    
    def get_estadisticas_votacion(self, mp_uid: int) -> Dict:
        """Obtiene estadísticas agregadas de votación del parlamentario."""
        query = """
            WITH votacion_stats AS (
                SELECT 
                    voto,
                    COUNT(*) as cantidad
                FROM votos_parlamentario
                WHERE mp_uid = ?
                GROUP BY voto
            ),
            total_votaciones AS (
                SELECT COUNT(DISTINCT sesion_votacion_id) as total
                FROM votos_parlamentario
                WHERE mp_uid = ?
            )
            SELECT 
                tv.total as total_votaciones,
                COALESCE(MAX(CASE WHEN vs.voto = 'A Favor' THEN vs.cantidad END), 0) as votos_a_favor,
                COALESCE(MAX(CASE WHEN vs.voto = 'En Contra' THEN vs.cantidad END), 0) as votos_en_contra,
                COALESCE(MAX(CASE WHEN vs.voto = 'Abstención' THEN vs.cantidad END), 0) as abstenciones,
                COALESCE(MAX(CASE WHEN vs.voto = 'Pareo' THEN vs.cantidad END), 0) as pareos
            FROM total_votaciones tv
            LEFT JOIN votacion_stats vs ON 1=1
        """
        self.cursor.execute(query, (mp_uid, mp_uid))
        return self._dict_from_row(self.cursor.fetchone())
    
    def get_votaciones_recientes(self, mp_uid: int, limite: int = 20) -> List[Dict]:
        """Obtiene las votaciones más recientes del parlamentario."""
        query = """
            SELECT 
                sv.sesion_votacion_id,
                sv.bill_id,
                sv.fecha,
                sv.tema,
                sv.resultado_general,
                sv.quorum_aplicado,
                vp.voto,
                b.titulo as titulo_proyecto,
                -- Calcular si votó con la mayoría
                CASE 
                    WHEN sv.resultado_general = 'Aprobado' AND vp.voto = 'A Favor' THEN 'Con mayoría'
                    WHEN sv.resultado_general = 'Rechazado' AND vp.voto = 'En Contra' THEN 'Con mayoría'
                    WHEN vp.voto IN ('Abstención', 'Pareo') THEN 'No aplicable'
                    ELSE 'Contra mayoría'
                END as alineacion_voto
            FROM votos_parlamentario vp
            JOIN sesiones_votacion sv ON vp.sesion_votacion_id = sv.sesion_votacion_id
            LEFT JOIN bills b ON sv.bill_id = b.bill_id
            WHERE vp.mp_uid = ?
            ORDER BY sv.fecha DESC
            LIMIT ?
        """
        self.cursor.execute(query, (mp_uid, limite))
        return [self._dict_from_row(row) for row in self.cursor.fetchall()]
    
    def get_comparacion_partidaria(self, mp_uid: int) -> Dict:
        """Analiza cómo vota en comparación con su partido actual."""
        query = """
            WITH partido_actual AS (
                SELECT p.partido_id, p.nombre_partido
                FROM militancia_historial mh
                JOIN dim_partidos p ON mh.partido_id = p.partido_id
                WHERE mh.mp_uid = ? 
                AND (mh.fecha_fin IS NULL OR mh.fecha_fin >= date('now'))
                LIMIT 1
            ),
            companeros_partido AS (
                SELECT DISTINCT mh.mp_uid
                FROM militancia_historial mh
                JOIN partido_actual pa ON mh.partido_id = pa.partido_id
                WHERE mh.fecha_fin IS NULL OR mh.fecha_fin >= date('now')
            ),
            votaciones_compartidas AS (
                SELECT 
                    vp1.sesion_votacion_id,
                    vp1.voto as voto_parlamentario,
                    vp2.voto as voto_companero,
                    CASE 
                        WHEN vp1.voto = vp2.voto THEN 1 
                        ELSE 0 
                    END as coincide
                FROM votos_parlamentario vp1
                JOIN votos_parlamentario vp2 
                    ON vp1.sesion_votacion_id = vp2.sesion_votacion_id
                JOIN companeros_partido cp 
                    ON vp2.mp_uid = cp.mp_uid
                WHERE vp1.mp_uid = ?
                    AND vp2.mp_uid != ?
            )
            SELECT 
                pa.nombre_partido,
                COUNT(DISTINCT vc.sesion_votacion_id) as votaciones_analizadas,
                AVG(vc.coincide) * 100 as porcentaje_coincidencia,
                SUM(vc.coincide) as votos_coincidentes,
                COUNT(*) as total_comparaciones
            FROM votaciones_compartidas vc
            CROSS JOIN partido_actual pa
            GROUP BY pa.nombre_partido
        """
        self.cursor.execute(query, (mp_uid, mp_uid, mp_uid))
        return self._dict_from_row(self.cursor.fetchone())
    
    def get_actividad_legislativa_resumen(self, mp_uid: int) -> Dict:
        """Genera un resumen de la actividad legislativa del parlamentario."""
        # Proyectos como autor
        query_proyectos = """
            SELECT 
                COUNT(*) as total_proyectos,
                SUM(CASE WHEN b.ley_numero IS NOT NULL THEN 1 ELSE 0 END) as proyectos_ley,
                SUM(CASE WHEN b.resultado_final = 'En tramitación' THEN 1 ELSE 0 END) as en_tramitacion,
                SUM(CASE WHEN b.iniciativa = 'Moción' THEN 1 ELSE 0 END) as mociones,
                SUM(CASE WHEN b.iniciativa = 'Mensaje' THEN 1 ELSE 0 END) as mensajes
            FROM bills b
            JOIN bill_authors ba ON b.bill_id = ba.bill_id
            WHERE ba.mp_uid = ?
        """
        self.cursor.execute(query_proyectos, (mp_uid,))
        proyectos = self._dict_from_row(self.cursor.fetchone())
        
        # Actividad en comisiones
        query_comisiones = """
            SELECT 
                COUNT(DISTINCT comision_id) as total_comisiones,
                SUM(CASE WHEN rol = 'Presidente' THEN 1 ELSE 0 END) as presidencias,
                SUM(CASE WHEN fecha_fin IS NULL THEN 1 ELSE 0 END) as comisiones_activas
            FROM comision_membresias
            WHERE mp_uid = ?
        """
        self.cursor.execute(query_comisiones, (mp_uid,))
        comisiones = self._dict_from_row(self.cursor.fetchone())
        
        return {
            'proyectos': proyectos,
            'comisiones': comisiones
        }
    
    def build_complete_context(self, mp_uid: int) -> Dict[str, Any]:
        """
        Construye el contexto completo para un parlamentario.
        Este es el método principal que orquesta todas las consultas.
        """
        print(f"🔨 Construyendo contexto para parlamentario con mp_uid={mp_uid}")
        
        # Verificar que el parlamentario existe
        perfil = self.get_perfil_basico(mp_uid)
        if not perfil:
            return {
                'error': f'No se encontró parlamentario con mp_uid={mp_uid}',
                'timestamp': datetime.now().isoformat()
            }
        
        print(f"   ✓ Perfil básico: {perfil['nombre_completo']}")
        
        # Construir el contexto completo
        context = {
            'metadata': {
                'mp_uid': mp_uid,
                'generated_at': datetime.now().isoformat(),
                'source': 'parlamento.db'
            },
            'perfil_biografico': perfil,
            'trayectoria': {
                'mandatos': self.get_mandatos_historicos(mp_uid),
                'militancia_partidaria': self.get_militancia_historica(mp_uid),
                'comisiones': self.get_comisiones(mp_uid)
            },
            'actividad_legislativa': {
                'resumen': self.get_actividad_legislativa_resumen(mp_uid),
                'proyectos_autor': self.get_proyectos_autor(mp_uid),
                'estadisticas_votacion': self.get_estadisticas_votacion(mp_uid),
                'votaciones_recientes': self.get_votaciones_recientes(mp_uid),
                'analisis_partidario': self.get_comparacion_partidaria(mp_uid)
            }
        }
        
        print(f"   ✓ Contexto completo generado")
        return context
    
    def export_context_to_json(self, mp_uid: int, output_path: Optional[str] = None) -> str:
        """
        Exporta el contexto a un archivo JSON.
        """
        context = self.build_complete_context(mp_uid)
        
        if output_path is None:
            output_dir = os.path.join(PROJECT_ROOT, 'data', 'contexts')
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(
                output_dir, 
                f"context_mp_{mp_uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(context, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"   ✓ Contexto exportado a: {output_path}")
        return output_path
    
    def export_context_to_text(self, mp_uid: int, output_path: Optional[str] = None) -> str:
        """
        Exporta el contexto a un formato de texto legible para el prompt.
        """
        context = self.build_complete_context(mp_uid)
        
        if 'error' in context:
            return context['error']
        
        # Construir texto estructurado
        lines = []
        lines.append("=" * 80)
        lines.append(f"CONTEXTO PARLAMENTARIO - {context['perfil_biografico']['nombre_completo']}")
        lines.append("=" * 80)
        lines.append(f"Generado: {context['metadata']['generated_at']}")
        lines.append("")
        
        # Perfil Biográfico
        lines.append("## PERFIL BIOGRÁFICO")
        lines.append("-" * 40)
        perfil = context['perfil_biografico']
        lines.append(f"Nombre Completo: {perfil['nombre_completo']}")
        lines.append(f"Género: {perfil['genero']}")
        if perfil.get('edad'):
            lines.append(f"Edad: {perfil['edad']} años")
        if perfil.get('fecha_nacimiento'):
            lines.append(f"Fecha de Nacimiento: {perfil['fecha_nacimiento']}")
        if perfil.get('lugar_nacimiento'):
            lines.append(f"Lugar de Nacimiento: {perfil['lugar_nacimiento']}")
        if perfil.get('profesion'):
            lines.append(f"Profesión: {perfil['profesion']}")
        if perfil.get('twitter_handle'):
            lines.append(f"Twitter: @{perfil['twitter_handle']}")
        lines.append("")
        
        # Trayectoria Política
        lines.append("## TRAYECTORIA POLÍTICA")
        lines.append("-" * 40)
        
        # Mandatos
        lines.append("### Mandatos Parlamentarios:")
        for mandato in context['trayectoria']['mandatos']:
            lines.append(f"  • {mandato['cargo']} - Distrito {mandato['distrito']} "
                        f"({mandato['fecha_inicio']} - {mandato['fecha_fin'] or 'Actual'}) "
                        f"[{mandato['estado_mandato']}]")
        lines.append("")
        
        # Militancia
        lines.append("### Militancia Partidaria:")
        for militancia in context['trayectoria']['militancia_partidaria']:
            lines.append(f"  • {militancia['nombre_partido']} "
                        f"({militancia['fecha_inicio']} - {militancia['fecha_fin'] or 'Actual'}) "
                        f"[{militancia['estado_militancia']}]")
        lines.append("")
        
        # Comisiones
        if context['trayectoria']['comisiones']:
            lines.append("### Participación en Comisiones:")
            for comision in context['trayectoria']['comisiones']:
                lines.append(f"  • {comision['nombre_comision']} - {comision['rol']} "
                            f"[{comision['estado_membresia']}]")
            lines.append("")
        
        # Actividad Legislativa
        lines.append("## ACTIVIDAD LEGISLATIVA")
        lines.append("-" * 40)
        
        resumen = context['actividad_legislativa']['resumen']
        lines.append("### Resumen de Actividad:")
        lines.append(f"  • Total de proyectos como autor/coautor: {resumen['proyectos']['total_proyectos']}")
        lines.append(f"  • Proyectos convertidos en ley: {resumen['proyectos']['proyectos_ley']}")
        lines.append(f"  • Proyectos en tramitación: {resumen['proyectos']['en_tramitacion']}")
        lines.append(f"  • Comisiones totales: {resumen['comisiones']['total_comisiones']}")
        lines.append(f"  • Presidencias de comisión: {resumen['comisiones']['presidencias']}")
        lines.append("")
        
        # Estadísticas de Votación
        stats = context['actividad_legislativa']['estadisticas_votacion']
        if stats and stats.get('total_votaciones'):
            lines.append("### Estadísticas de Votación:")
            lines.append(f"  • Total de votaciones: {stats['total_votaciones']}")
            lines.append(f"  • Votos a favor: {stats['votos_a_favor']}")
            lines.append(f"  • Votos en contra: {stats['votos_en_contra']}")
            lines.append(f"  • Abstenciones: {stats['abstenciones']}")
            lines.append(f"  • Pareos: {stats['pareos']}")
            lines.append("")
        
        # Análisis Partidario
        analisis = context['actividad_legislativa']['analisis_partidario']
        if analisis and analisis.get('nombre_partido'):
            lines.append("### Coherencia con Partido:")
            lines.append(f"  • Partido: {analisis['nombre_partido']}")
            lines.append(f"  • Coincidencia con partido: {analisis['porcentaje_coincidencia']:.1f}%")
            lines.append(f"  • Votaciones analizadas: {analisis['votaciones_analizadas']}")
            lines.append("")
        
        # Proyectos Recientes (solo primeros 5)
        lines.append("### Proyectos de Ley como Autor (más recientes):")
        for proyecto in context['actividad_legislativa']['proyectos_autor'][:5]:
            lines.append(f"  • [{proyecto['bill_id']}] {proyecto['titulo'][:80]}...")
            lines.append(f"    Fecha: {proyecto['fecha_ingreso']} | Estado: {proyecto['etapa'] or 'Sin información'}")
        lines.append("")
        
        lines.append("=" * 80)
        lines.append("FIN DEL CONTEXTO")
        lines.append("=" * 80)
        
        # Guardar a archivo si se especifica
        if output_path is None:
            output_dir = os.path.join(PROJECT_ROOT, 'data', 'contexts')
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(
                output_dir, 
                f"context_mp_{mp_uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            )
        
        text_content = '\n'.join(lines)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(text_content)
        
        print(f"   ✓ Contexto de texto exportado a: {output_path}")
        return text_content


def main():
    """
    Función principal para uso desde línea de comandos.
    """
    import sys
    
    # Verificar argumentos
    if len(sys.argv) < 2:
        print("Uso: python context_builder.py <mp_uid> [formato]")
        print("  mp_uid: ID único del parlamentario")
        print("  formato: 'json' (default), 'text', o 'both'")
        print("\nEjemplo: python context_builder.py 1 both")
        sys.exit(1)
    
    try:
        mp_uid = int(sys.argv[1])
        formato = sys.argv[2] if len(sys.argv) > 2 else 'json'
        
        with ParlamentarioContextBuilder() as builder:
            if formato in ['json', 'both']:
                json_path = builder.export_context_to_json(mp_uid)
                print(f"✅ Contexto JSON generado: {json_path}")
            
            if formato in ['text', 'both']:
                text_path = builder.export_context_to_text(mp_uid)
                print(f"✅ Contexto de texto generado: {text_path}")
            
            if formato == 'print':
                # Solo imprimir en consola
                context = builder.build_complete_context(mp_uid)
                print(json.dumps(context, ensure_ascii=False, indent=2, default=str))
                
    except ValueError:
        print(f"Error: mp_uid debe ser un número entero")
        sys.exit(1)
    except Exception as e:
        print(f"Error al generar contexto: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()