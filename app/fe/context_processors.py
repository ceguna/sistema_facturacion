from .models import Empresa


def empresa_branding(request):
    """
    Inyecta la Empresa configurada en TODAS las plantillas -- agregado
    17/09/2026 para que base.html pueda mostrar el logo y la razon
    social real del cliente en el sidebar, en vez del texto fijo "CGS
    Gestión" (que solo tiene sentido para nuestro propio uso interno,
    no para un cliente que compre el sistema). Sin esto, cada vista
    tendria que acordarse de pasar 'empresa' a mano.
    """
    return {'empresa_actual': Empresa.objects.first()}
