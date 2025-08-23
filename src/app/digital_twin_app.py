# src/app/digital_twin_app.py
# -*- coding: utf-8 -*-

"""
Digital Twin Parlamentario - Aplicación de Chat Interactivo v2.0

Aplicación Streamlit que implementa un gemelo digital de parlamentarios chilenos
con capacidades de RAG, contexto enriquecido y personalización avanzada.
"""

import streamlit as st
import sqlite3
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import time

# Añadir el directorio raíz al path para imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from src.core.context_builder import ParlamentarioContextBuilder

# Configuración de la página debe ir PRIMERO
st.set_page_config(
    page_title="Digital Twin Parlamentario",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONFIGURACIÓN ---
DB_PATH = os.path.join(PROJECT_ROOT, 'data', 'database', 'parlamento.db')
CACHE_DIR = os.path.join(PROJECT_ROOT, 'data', 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# Intentar importar ollama, si no está disponible, usar modo simulado
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    st.warning("⚠️ Ollama no está instalado. Ejecutando en modo simulación.")


class DigitalTwinChatbot:
    """
    Clase principal para el chatbot de gemelo digital con capacidades RAG mejoradas.
    """
    
    def __init__(self, mp_uid: int):
        self.mp_uid = mp_uid
        self.context = None
        self.context_text = None
        self.parlamentario_info = None
        self.conversation_history = []
        self._load_context()
    
    def _load_context(self):
        """Carga el contexto del parlamentario."""
        with ParlamentarioContextBuilder() as builder:
            self.context = builder.build_complete_context(self.mp_uid)
            
            # Generar versión de texto para el prompt
            if 'error' not in self.context:
                self.parlamentario_info = self.context['perfil_biografico']
                self.context_text = self._format_context_for_prompt()
    
    def _format_context_for_prompt(self) -> str:
        """Formatea el contexto de manera optimizada para el LLM."""
        lines = []
        
        # Información biográfica esencial
        perfil = self.context['perfil_biografico']
        lines.append(f"IDENTIDAD: {perfil['nombre_completo']}")
        lines.append(f"GÉNERO: {perfil['genero']}")
        if perfil.get('profesion'):
            lines.append(f"PROFESIÓN: {perfil['profesion']}")
        if perfil.get('fecha_nacimiento'):
            lines.append(f"FECHA DE NACIMIENTO: {perfil['fecha_nacimiento']}")
        
        # Partido actual
        militancias = self.context['trayectoria']['militancia_partidaria']
        for m in militancias:
            if m['estado_militancia'] == 'Actual':
                lines.append(f"PARTIDO ACTUAL: {m['nombre_partido']}")
                break
        
        # Mandato actual
        mandatos = self.context['trayectoria']['mandatos']
        for m in mandatos:
            if m['estado_mandato'] == 'Activo':
                lines.append(f"CARGO ACTUAL: {m['cargo']} - Distrito {m['distrito']}")
                break
        
        # Comisiones actuales
        lines.append("\nCOMISIONES ACTUALES:")
        for c in self.context['trayectoria']['comisiones']:
            if c['estado_membresia'] == 'Activo':
                lines.append(f"- {c['nombre_comision']} ({c['rol']})")
        
        # Estadísticas clave
        resumen = self.context['actividad_legislativa']['resumen']
        lines.append(f"\nPROYECTOS DE LEY PRESENTADOS: {resumen['proyectos']['total_proyectos']}")
        lines.append(f"PROYECTOS CONVERTIDOS EN LEY: {resumen['proyectos']['proyectos_ley']}")
        
        # Estadísticas de votación
        stats = self.context['actividad_legislativa']['estadisticas_votacion']
        if stats and stats.get('total_votaciones'):
            lines.append(f"\nTOTAL DE VOTACIONES: {stats['total_votaciones']}")
            lines.append(f"VOTOS A FAVOR: {stats['votos_a_favor']}")
            lines.append(f"VOTOS EN CONTRA: {stats['votos_en_contra']}")
        
        # Proyectos destacados (últimos 3)
        lines.append("\nPROYECTOS RECIENTES COMO AUTOR:")
        for p in self.context['actividad_legislativa']['proyectos_autor'][:3]:
            lines.append(f"- [{p['bill_id']}] {p['titulo'][:100]}")
        
        return '\n'.join(lines)
    
    def _extract_relevant_context(self, query: str) -> str:
        """
        Extrae el contexto más relevante basado en la consulta del usuario.
        Implementación básica de RAG sin vectores.
        """
        query_lower = query.lower()
        relevant_parts = []
        
        # Palabras clave para diferentes tipos de información
        keywords = {
            'votacion': ['votación', 'votar', 'voto', 'votado', 'voté', 'votamos'],
            'proyecto': ['proyecto', 'ley', 'propuesta', 'iniciativa', 'bill'],
            'comision': ['comisión', 'comisiones', 'preside', 'presidir'],
            'partido': ['partido', 'militancia', 'afiliación', 'bancada'],
            'biografia': ['edad', 'nacimiento', 'profesión', 'estudios', 'vida']
        }
        
        # Determinar qué secciones son relevantes
        relevant_sections = set()
        for section, words in keywords.items():
            if any(word in query_lower for word in words):
                relevant_sections.add(section)
        
        # Si no hay secciones específicas, usar contexto general
        if not relevant_sections:
            return self.context_text
        
        # Construir contexto relevante
        if 'biografia' in relevant_sections:
            relevant_parts.append(self._get_biografia_context())
        if 'partido' in relevant_sections:
            relevant_parts.append(self._get_partido_context())
        if 'comision' in relevant_sections:
            relevant_parts.append(self._get_comisiones_context())
        if 'proyecto' in relevant_sections:
            relevant_parts.append(self._get_proyectos_context())
        if 'votacion' in relevant_sections:
            relevant_parts.append(self._get_votaciones_context())
        
        return '\n\n'.join(relevant_parts) if relevant_parts else self.context_text
    
    def _get_biografia_context(self) -> str:
        """Extrae contexto biográfico."""
        perfil = self.context['perfil_biografico']
        return f"""INFORMACIÓN BIOGRÁFICA:
- Nombre: {perfil['nombre_completo']}
- Género: {perfil['genero']}
- Fecha de nacimiento: {perfil.get('fecha_nacimiento', 'No disponible')}
- Lugar de nacimiento: {perfil.get('lugar_nacimiento', 'No disponible')}
- Profesión: {perfil.get('profesion', 'No disponible')}
- Edad: {perfil.get('edad', 'No disponible')} años"""
    
    def _get_partido_context(self) -> str:
        """Extrae contexto de militancia partidaria."""
        lines = ["HISTORIAL DE MILITANCIA:"]
        for m in self.context['trayectoria']['militancia_partidaria']:
            lines.append(f"- {m['nombre_partido']} ({m['fecha_inicio']} - {m['fecha_fin'] or 'Actual'})")
        
        analisis = self.context['actividad_legislativa']['analisis_partidario']
        if analisis and analisis.get('nombre_partido'):
            lines.append(f"\nCOHERENCIA CON PARTIDO ACTUAL:")
            lines.append(f"- Coincidencia en votaciones: {analisis['porcentaje_coincidencia']:.1f}%")
        
        return '\n'.join(lines)
    
    def _get_comisiones_context(self) -> str:
        """Extrae contexto de comisiones."""
        lines = ["PARTICIPACIÓN EN COMISIONES:"]
        for c in self.context['trayectoria']['comisiones']:
            estado = " (ACTUAL)" if c['estado_membresia'] == 'Activo' else ""
            lines.append(f"- {c['nombre_comision']} - {c['rol']}{estado}")
        return '\n'.join(lines)
    
    def _get_proyectos_context(self) -> str:
        """Extrae contexto de proyectos de ley."""
        lines = ["PROYECTOS DE LEY COMO AUTOR:"]
        resumen = self.context['actividad_legislativa']['resumen']['proyectos']
        lines.append(f"Total presentados: {resumen['total_proyectos']}")
        lines.append(f"Convertidos en ley: {resumen['proyectos_ley']}")
        lines.append(f"En tramitación: {resumen['en_tramitacion']}")
        
        lines.append("\nÚLTIMOS 5 PROYECTOS:")
        for p in self.context['actividad_legislativa']['proyectos_autor'][:5]:
            lines.append(f"- [{p['bill_id']}] {p['titulo'][:80]}...")
            if p['ley_numero']:
                lines.append(f"  → Convertido en Ley N° {p['ley_numero']}")
        
        return '\n'.join(lines)
    
    def _get_votaciones_context(self) -> str:
        """Extrae contexto de votaciones."""
        stats = self.context['actividad_legislativa']['estadisticas_votacion']
        lines = ["ESTADÍSTICAS DE VOTACIÓN:"]
        if stats:
            total = stats.get('total_votaciones', 0)
            if total > 0:
                lines.append(f"- Total de votaciones: {total}")
                lines.append(f"- A favor: {stats['votos_a_favor']} ({100*stats['votos_a_favor']/total:.1f}%)")
                lines.append(f"- En contra: {stats['votos_en_contra']} ({100*stats['votos_en_contra']/total:.1f}%)")
                lines.append(f"- Abstenciones: {stats['abstenciones']}")
        
        lines.append("\nÚLTIMAS VOTACIONES:")
        for v in self.context['actividad_legislativa']['votaciones_recientes'][:5]:
            lines.append(f"- {v['fecha']}: {v['tema'][:60]}... → Voté: {v['voto']}")
        
        return '\n'.join(lines)
    
    def chat(self, user_query: str, use_rag: bool = True, temperature: float = 0.7) -> str:
        """
        Procesa una consulta del usuario y genera una respuesta.
        """
        if not self.context_text:
            return "Error: No se pudo cargar el contexto del parlamentario."
        
        # Extraer contexto relevante si RAG está habilitado
        context_to_use = self._extract_relevant_context(user_query) if use_rag else self.context_text
        
        # Construir el prompt del sistema
        system_prompt = f"""Eres el gemelo digital del parlamentario {self.parlamentario_info['nombre_completo']}.
        
INSTRUCCIONES:
1. Responde SIEMPRE en primera persona, como si fueras el/la parlamentario
2. Basa tus respuestas ÚNICAMENTE en la información del contexto proporcionado
3. Si no tienes información sobre algo, dilo honestamente
4. Mantén un tono profesional pero cercano
5. Sé específico y menciona datos concretos cuando sea relevante
6. NO inventes información que no esté en el contexto

CONTEXTO RELEVANTE:
{context_to_use}

HISTORIAL DE CONVERSACIÓN:
{self._format_conversation_history()}"""
        
        # Si Ollama está disponible, usar el modelo real
        if OLLAMA_AVAILABLE:
            try:
                response = ollama.chat(
                    model='qwen2.5:7b',  # Puedes cambiar el modelo
                    messages=[
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_query}
                    ],
                    options={
                        'temperature': temperature,
                        'top_p': 0.9,
                        'max_tokens': 500
                    },
                    stream=False
                )
                answer = response['message']['content']
            except Exception as e:
                answer = f"Error al conectar con Ollama: {str(e)}"
        else:
            # Modo simulación para desarrollo
            answer = self._simulate_response(user_query, context_to_use)
        
        # Guardar en historial
        self.conversation_history.append({
            'user': user_query,
            'assistant': answer,
            'timestamp': datetime.now().isoformat()
        })
        
        return answer
    
    def _format_conversation_history(self) -> str:
        """Formatea el historial de conversación para el contexto."""
        if not self.conversation_history:
            return "Sin conversación previa."
        
        # Solo incluir las últimas 3 interacciones para no sobrecargar el contexto
        recent = self.conversation_history[-3:]
        lines = []
        for exchange in recent:
            lines.append(f"Usuario: {exchange['user']}")
            lines.append(f"Yo: {exchange['assistant'][:200]}...")
            lines.append("")
        
        return '\n'.join(lines)
    
    def _simulate_response(self, query: str, context: str) -> str:
        """Simula una respuesta cuando Ollama no está disponible."""
        query_lower = query.lower()
        
        # Respuestas simuladas basadas en palabras clave
        if any(word in query_lower for word in ['proyecto', 'ley', 'propuesta']):
            resumen = self.context['actividad_legislativa']['resumen']['proyectos']
            return f"""Como parlamentario, he presentado {resumen['total_proyectos']} proyectos de ley, 
de los cuales {resumen['proyectos_ley']} se han convertido en ley. 
Actualmente tengo {resumen['en_tramitacion']} proyectos en tramitación. 
Mi trabajo legislativo se ha enfocado en mejorar la calidad de vida de los ciudadanos de mi distrito."""
        
        elif any(word in query_lower for word in ['votación', 'votar', 'voto']):
            stats = self.context['actividad_legislativa']['estadisticas_votacion']
            if stats and stats.get('total_votaciones'):
                return f"""He participado en {stats['total_votaciones']} votaciones en el Congreso. 
Mi historial muestra {stats['votos_a_favor']} votos a favor, {stats['votos_en_contra']} en contra, 
y {stats['abstenciones']} abstenciones. Siempre voto pensando en el beneficio de mis representados."""
        
        elif any(word in query_lower for word in ['comisión', 'comisiones']):
            comisiones_activas = [c for c in self.context['trayectoria']['comisiones'] 
                                 if c['estado_membresia'] == 'Activo']
            if comisiones_activas:
                nombres = [c['nombre_comision'] for c in comisiones_activas[:3]]
                return f"""Actualmente participo en {len(comisiones_activas)} comisiones parlamentarias, 
incluyendo: {', '.join(nombres)}. Mi trabajo en comisiones es fundamental para el análisis 
detallado de los proyectos de ley."""
        
        # Respuesta genérica
        return f"""Soy {self.parlamentario_info['nombre_completo']}, parlamentario de la República. 
Estoy aquí para responder tus preguntas sobre mi trabajo legislativo y trayectoria política. 
¿En qué puedo ayudarte específicamente?"""


def get_available_parlamentarios() -> List[Tuple[int, str]]:
    """Obtiene la lista de parlamentarios disponibles."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT mp_uid, nombre_completo 
            FROM dim_parlamentario 
            ORDER BY nombre_completo
        """)
        return cursor.fetchall()


def main():
    """Función principal de la aplicación Streamlit."""
    
    # --- HEADER ---
    st.title("🏛️ Digital Twin Parlamentario")
    st.markdown("**Chat interactivo con gemelos digitales de parlamentarios chilenos**")
    
    # --- SIDEBAR ---
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        # Selector de parlamentario
        parlamentarios = get_available_parlamentarios()
        
        if not parlamentarios:
            st.error("No hay parlamentarios en la base de datos")
            return
        
        # Crear diccionario para el selector
        options_dict = {f"{nombre} (ID: {uid})": uid for uid, nombre in parlamentarios}
        
        selected_option = st.selectbox(
            "Seleccionar Parlamentario:",
            options=list(options_dict.keys()),
            help="Elige el parlamentario con quien quieres conversar"
        )
        
        selected_mp_uid = options_dict[selected_option]
        
        # Opciones avanzadas
        st.markdown("### 🎛️ Opciones Avanzadas")
        
        use_rag = st.checkbox(
            "Usar RAG (Contexto Relevante)",
            value=True,
            help="Extrae automáticamente el contexto más relevante para cada pregunta"
        )
        
        temperature = st.slider(
            "Temperatura (Creatividad)",
            min_value=0.0,
            max_value=1.0,
            value=0.7,
            step=0.1,
            help="Valores más bajos = respuestas más conservadoras"
        )
        
        # Botón para limpiar conversación
        if st.button("🗑️ Limpiar Conversación"):
            st.session_state.messages = []
            st.session_state.chatbot = None
            st.rerun()
        
        # Información del parlamentario seleccionado
        st.markdown("### 📊 Información del Parlamentario")
        
        if 'chatbot' not in st.session_state or st.session_state.current_mp != selected_mp_uid:
            with st.spinner("Cargando información..."):
                st.session_state.chatbot = DigitalTwinChatbot(selected_mp_uid)
                st.session_state.current_mp = selected_mp_uid
                st.session_state.messages = []
        
        chatbot = st.session_state.chatbot
        
        if chatbot.parlamentario_info:
            info = chatbot.parlamentario_info
            
            # Mostrar foto si está disponible
            if info.get('url_foto'):
                st.image(info['url_foto'], width=150)
            
            st.markdown(f"**Nombre:** {info['nombre_completo']}")
            st.markdown(f"**Género:** {info['genero']}")
            if info.get('profesion'):
                st.markdown(f"**Profesión:** {info['profesion']}")
            if info.get('edad'):
                st.markdown(f"**Edad:** {info['edad']} años")
            
            # Mostrar estadísticas clave
            if chatbot.context:
                resumen = chatbot.context['actividad_legislativa']['resumen']
                st.markdown("### 📈 Estadísticas")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Proyectos de Ley", resumen['proyectos']['total_proyectos'])
                    st.metric("Comisiones", resumen['comisiones']['total_comisiones'])
                with col2:
                    st.metric("Leyes Aprobadas", resumen['proyectos']['proyectos_ley'])
                    st.metric("Presidencias", resumen['comisiones']['presidencias'])
    
    # --- MAIN CHAT AREA ---
    st.markdown("---")
    
    # Inicializar historial de mensajes
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Mostrar mensajes anteriores
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Input del usuario
    if prompt := st.chat_input("Hazle una pregunta al parlamentario..."):
        # Añadir mensaje del usuario
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Generar respuesta
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                response = chatbot.chat(prompt, use_rag=use_rag, temperature=temperature)
                st.markdown(response)
        
        # Añadir respuesta al historial
        st.session_state.messages.append({"role": "assistant", "content": response})
    
    # --- FOOTER ---
    st.markdown("---")
    with st.expander("ℹ️ Acerca de esta aplicación"):
        st.markdown("""
        Esta aplicación crea un "gemelo digital" de parlamentarios chilenos usando:
        - 🗃️ **Base de datos** con información legislativa completa
        - 🔍 **RAG** (Retrieval-Augmented Generation) para contexto relevante
        - 🤖 **LLM** (Large Language Model) para generar respuestas naturales
        - 📊 **Datos reales** de votaciones, proyectos y comisiones
        
        **Nota:** Las respuestas se basan únicamente en datos oficiales disponibles.
        El parlamentario real no ha validado estas respuestas.
        """)
    
    # Mostrar modo de operación
    if not OLLAMA_AVAILABLE:
        st.info("🔧 Ejecutando en modo simulación (Ollama no detectado)")


if __name__ == "__main__":
    main()