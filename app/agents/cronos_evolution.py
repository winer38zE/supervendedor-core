# app/agents/cronos_evolution.py
import random
import json
from vertexai.generative_models import GenerativeModel

class CronosEvolution:
    def __init__(self):
        # Cronos necesita la máxima inteligencia para mutar los conceptos
        self.model = GenerativeModel("gemini-1.5-pro")
        self.system_brain_file = "system_prompt_v2.txt"

    def load_successful_scripts(self, log_data: list) -> list:
        """Carga scripts del día que resultaron en venta exitosa (la 'Selección Natural')."""
        
        # En la vida real, 'log_data' sería un archivo de Supabase o un log
        successful_scripts = [
            log['script_used'] 
            for log in log_data 
            if log['status'] == "VENTA_EXITOSA"
        ]
        return successful_scripts

    def crossover(self, parent_a: str, parent_b: str) -> str:
        """Combina dos scripts exitosos para crear un 'hijo' (Cruce)."""
        
        parts_a = parent_a.split('.')
        parts_b = parent_b.split('.')
        
        if not parts_a or not parts_b:
             return random.choice([parent_a, parent_b])
             
        # Tomamos el inicio del primer padre y el final del segundo padre
        child_script = parts_a[0] + ". " + parts_b[-1]
        return child_script

    def mutate_script_with_ai(self, script_fragment: str) -> str:
        """Usa Gemini para reescribir creativamente una frase (Mutación)."""
        
        prompt = (
            f"Eres un editor de guiones de ventas de élite. Toma esta frase: '{script_fragment}'. "
            f"Reescríbela de una forma más corta, más urgente o con mayor valor percibido, manteniendo la idea central."
        )
        
        response = self.model.generate_content(prompt, temperature=0.9).text
        return response.strip()

    def evolve_brain(self, daily_log_data: list):
        """Ejecuta el ciclo evolutivo y actualiza el cerebro de Zeus."""
        
        successful = self.load_successful_scripts(daily_log_data)
        
        if len(successful) < 2:
            print("Cronos: No hay suficientes datos para la evolución. ¡Necesitamos más ventas!")
            return

        # 1. Cruzamos a los dos mejores
        parent_a = successful[0]
        parent_b = successful[-1]
        new_script = self.crossover(parent_a, parent_b)
        
        # 2. Mutamos el nuevo script
        evolved_script = self.mutate_script_with_ai(new_script)
        
        # 3. Guardamos el nuevo cerebro para mañana
        with open(self.system_brain_file, "w") as f:
            f.write(evolved_script)
            
        print(f"🧬 Cronos: Evolución completada. Nuevo script para mañana guardado en {self.system_brain_file}")# app/agents/cronos_evolution.py
import random
import json
from vertexai.generative_models import GenerativeModel

class CronosEvolution:
    def __init__(self):
        # Cronos necesita la máxima inteligencia para mutar los conceptos
        self.model = GenerativeModel("gemini-1.5-pro")
        self.system_brain_file = "system_prompt_v2.txt"

    def load_successful_scripts(self, log_data: list) -> list:
        """Carga scripts del día que resultaron en venta exitosa (la 'Selección Natural')."""
        
        # En la vida real, 'log_data' sería un archivo de Supabase o un log
        successful_scripts = [
            log['script_used'] 
            for log in log_data 
            if log['status'] == "VENTA_EXITOSA"
        ]
        return successful_scripts

    def crossover(self, parent_a: str, parent_b: str) -> str:
        """Combina dos scripts exitosos para crear un 'hijo' (Cruce)."""
        
        parts_a = parent_a.split('.')
        parts_b = parent_b.split('.')
        
        if not parts_a or not parts_b:
             return random.choice([parent_a, parent_b])
             
        # Tomamos el inicio del primer padre y el final del segundo padre
        child_script = parts_a[0] + ". " + parts_b[-1]
        return child_script

    def mutate_script_with_ai(self, script_fragment: str) -> str:
        """Usa Gemini para reescribir creativamente una frase (Mutación)."""
        
        prompt = (
            f"Eres un editor de guiones de ventas de élite. Toma esta frase: '{script_fragment}'. "
            f"Reescríbela de una forma más corta, más urgente o con mayor valor percibido, manteniendo la idea central."
        )
        
        response = self.model.generate_content(prompt, temperature=0.9).text
        return response.strip()

    def evolve_brain(self, daily_log_data: list):
        """Ejecuta el ciclo evolutivo y actualiza el cerebro de Zeus."""
        
        successful = self.load_successful_scripts(daily_log_data)
        
        if len(successful) < 2:
            print("Cronos: No hay suficientes datos para la evolución. ¡Necesitamos más ventas!")
            return

        # 1. Cruzamos a los dos mejores
        parent_a = successful[0]
        parent_b = successful[-1]
        new_script = self.crossover(parent_a, parent_b)
        
        # 2. Mutamos el nuevo script
        evolved_script = self.mutate_script_with_ai(new_script)
        
        # 3. Guardamos el nuevo cerebro para mañana
        with open(self.system_brain_file, "w") as f:
            f.write(evolved_script)
            
        print(f"🧬 Cronos: Evolución completada. Nuevo script para mañana guardado en {self.system_brain_file}")