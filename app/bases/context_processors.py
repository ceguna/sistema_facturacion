def sucursal_actual(request):
    """
    Inyecta la sucursal actual (Fase 2, 20/09/2026) y, solo para
    superusuarios, el listado completo de sucursales -- para que
    base.html pueda mostrar el selector en la barra superior sin que
    cada vista tenga que pasarlo a mano. Solo tiene sentido para un
    usuario logueado; en login/logout, `request.user` es anónimo y no
    tiene sesión de negocio todavía.
    """
    if not request.user.is_authenticated:
        return {}

    from .views import obtener_sucursal_actual

    contexto = {'sucursal_actual': obtener_sucursal_actual(request)}
    if request.user.is_superuser:
        from fe.models import Sucursal
        contexto['todas_sucursales'] = Sucursal.objects.all().order_by('codigo_sucursal')
    return contexto
