from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views import generic
from django.urls import reverse_lazy
from django.contrib import messages

# Se necesita importar el login required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth.decorators import login_required, permission_required

from .models import Categoria,SubCategoria, Marca, UnidadMedida, Producto
from .forms import CategoriaForm, SubCategoriaForm, MarcaForm, UnidadMedidaForm, ProductoForm

from bases.views import SinPrivilegios

class CategoriaView(SinPrivilegios,generic.ListView):
    permission_required = "inv.view_categoria"
    model = Categoria
    template_name = "inv/categoria_list.html"
    context_object_name = "obj"
    
class CategoriaNew(SuccessMessageMixin,SinPrivilegios,generic.CreateView):
    permission_required = "inv.add_categoria"
    model = Categoria
    template_name = "inv/categoria_form.html"
    context_object_name = "obj"
    form_class = CategoriaForm
    success_url = reverse_lazy("inv:categoria_list")
    success_message="Categoria Creada Satisfactoriamente"

    def form_valid(self, form):
        form.instance.uc = self.request.user
        return super().form_valid(form)
    
class CategoriaEdit(SuccessMessageMixin,SinPrivilegios,generic.UpdateView):
    permission_required = "inv.change_categoria"
    model = Categoria
    template_name = "inv/categoria_form.html"
    context_object_name = "obj"
    form_class = CategoriaForm
    success_url = reverse_lazy("inv:categoria_list")
    login_url = "bases:login"
    success_message="Categoria Actualizada Satisfactoriamente"

    def form_valid(self, form):
        form.instance.um = self.request.user.id
        return super().form_valid(form)
    
class CategoriaDel(SinPrivilegios, generic.DeleteView):
    permission_required = "inv.delete_categoria"
    model = Categoria
    template_name = "inv/catalogos_del.html"
    context_object_name = "obj"
    success_url = reverse_lazy("inv:categoria_list")

class SubCategoriaView(SinPrivilegios,generic.ListView):
    permission_required = "inv.view_subcategoria"
    model = SubCategoria
    template_name = "inv/subcategoria_list.html"
    context_object_name = "obj"

class SubCategoriaNew(SinPrivilegios, generic.CreateView):
    permission_required = "inv.add_subcategoria"
    model = SubCategoria
    template_name = "inv/subcategoria_form.html"
    context_object_name = "obj"
    form_class = SubCategoriaForm
    success_url = reverse_lazy("inv:subcategoria_list")
    login_url = "bases:login"

    def form_valid(self, form):
        form.instance.uc = self.request.user
        return super().form_valid(form)
    
class SubCategoriaEdit(SinPrivilegios, generic.UpdateView):
    permission_required = "inv.change_subcategoria"
    model = SubCategoria
    template_name = "inv/subcategoria_form.html"
    context_object_name = "obj"
    form_class = SubCategoriaForm
    success_url = reverse_lazy("inv:subcategoria_list")
    login_url = "bases:login"

    def form_valid(self, form):
        form.instance.um = self.request.user.id
        return super().form_valid(form)
    
class SubCategoriaDel(SinPrivilegios, generic.DeleteView):
    permission_required = "inv.delete_subcategoria"
    model = SubCategoria
    template_name = "inv/subcatalogos_del.html"
    context_object_name = "obj"
    success_url = reverse_lazy("inv:subcategoria_list")

class MarcaView(SinPrivilegios,generic.ListView):
    permission_required = "inv.view_marca"
    model = Marca
    template_name = "inv/marca_list.html"
    context_object_name = "obj"

class MarcaNew(SinPrivilegios, generic.CreateView):
    permission_required = "inv.add_marca"
    model = Marca
    template_name = "inv/marca_form.html"
    context_object_name = "obj"
    form_class = MarcaForm
    success_url = reverse_lazy("inv:marca_list")
    login_url = "bases:login"

    def form_valid(self, form):
        form.instance.uc = self.request.user
        return super().form_valid(form)
    
class MarcaEdit(SinPrivilegios, generic.UpdateView):
    permission_required = "inv.change_marca"
    model = Marca
    template_name = "inv/marca_form.html"
    context_object_name = "obj"
    form_class = MarcaForm
    success_url = reverse_lazy("inv:marca_list")
    login_url = "bases:login"

    def form_valid(self, form):
        form.instance.um = self.request.user.id
        return super().form_valid(form)

@login_required(login_url='/login/')
@permission_required('inv.change_marca',login_url='bases:sin_privilegios')

def marca_inactivar(request, id):
    marca = Marca.objects.filter(pk=id).first() #Una consulta a la base de datos mediante el ORM de django.
    contexto={} #El contexto esta vacio para poder rellenar
    template_name="inv/catalogos_inactivo.html"

    if not marca:
        return redirect("inv:marca_list")

    if request.method=='GET':
        contexto={'obj':marca}
    
    if request.method=='POST':
        marca.estado=False
        marca.save()
        messages.success(request, 'Marca Inactivada.')
        return redirect("inv:marca_list")

    return render(request,template_name,contexto)

class UMView(SinPrivilegios, generic.ListView):
    permission_required = "inv.view_unidadmedida"
    model = UnidadMedida
    template_name = "inv/um_list.html"
    context_object_name = "obj"
    login_url = "bases:login"

class UMNew(SinPrivilegios, generic.CreateView):
    permission_required = "inv.add_unidadmedida"
    model = UnidadMedida
    template_name = "inv/um_form.html"
    context_object_name = "obj"
    form_class = UnidadMedidaForm
    success_url = reverse_lazy("inv:um_list")
    login_url = "bases:login"

    def form_valid(self, form):
        form.instance.uc = self.request.user
        return super().form_valid(form)
    
class UMEdit(SinPrivilegios, generic.UpdateView):
    permission_required = "inv.change_unidadmedida"
    model = UnidadMedida
    template_name = "inv/um_form.html"
    context_object_name = "obj"
    form_class = UnidadMedidaForm
    success_url = reverse_lazy("inv:um_list")
    login_url = "bases:login"

    def form_valid(self, form):
        form.instance.um = self.request.user.id
        return super().form_valid(form)

@login_required(login_url='/login/')
@permission_required('inv.change_unidadmedida',login_url='bases:sin_privilegios')
def um_inactivar(request, id):
    um = UnidadMedida.objects.filter(pk=id).first() #Una consulta a la base de datos mediante el ORM de django.
    contexto={} #El contexto esta vacio para poder rellenar
    template_name="inv/catalogos_inactivo.html"

    if not um:
        return redirect("inv:um_list")

    if request.method=='GET':
        contexto={'obj':um}
    
    if request.method=='POST':
        um.estado=False
        um.save()
        return redirect("inv:um_list")

    return render(request,template_name,contexto)

class ProductoView(SinPrivilegios, generic.ListView):
    permission_required = "inv.view_producto"
    model = Producto
    template_name = "inv/producto_list.html"
    context_object_name = "obj"
    login_url = "bases:login"

class ProductoNew(SuccessMessageMixin,SinPrivilegios, generic.CreateView):
    permission_required = "inv.add_producto"
    model = Producto
    template_name = "inv/producto_form.html"
    context_object_name = "obj"
    form_class = ProductoForm
    success_url = reverse_lazy("inv:producto_list")
    login_url = "bases:login"
    success_message="Producto Creado Satisfactoriamente"

    def form_valid(self, form):
        form.instance.uc = self.request.user
        self.request.session['success_message'] = self.success_message

        redirect_url = reverse_lazy("inv:producto_list")

        response = JsonResponse({'redirect_url': redirect_url, 'success_message': self.success_message}, status=200)

        response['X-Redirect'] = redirect_url

        return super().form_valid(form)
    
    def get_context_data(self, **kwargs):
        context = super(ProductoNew, self).get_context_data(**kwargs)
        context["categorias"] = Categoria.objects.all()
        context["subcategorias"] = SubCategoria.objects.all()
        return context
    
class ProductoEdit(SuccessMessageMixin,SinPrivilegios, generic.UpdateView):
    permission_required = "inv.change_producto"
    model = Producto
    template_name = "inv/producto_form.html"
    context_object_name = "obj"
    form_class = ProductoForm
    success_url = reverse_lazy("inv:producto_list")
    login_url = "bases:login"
    success_message="Producto Actualizado Satisfactoriamente"

    def form_valid(self, form):
        form.instance.um = self.request.user.id
        return super().form_valid(form)
    
    def get_context_data(self, **kwargs):
        pk = self.kwargs.get('pk')
        
        context = super(ProductoEdit, self).get_context_data(**kwargs)
        context["categorias"] = Categoria.objects.all()
        context["subcategorias"] = SubCategoria.objects.all()
        context["obj"] = Producto.objects.filter(pk=pk).first()

        return context

@login_required(login_url='/login/')
@permission_required('inv.change_producto',login_url='bases:sin_privilegios')    
def producto_inactivar(request, id):
    prod = Producto.objects.filter(pk=id).first()
    contexto={}
    template_name="inv/catalogos_inactivo.html"

    if not prod:
        return redirect("inv:producto_list")

    if request.method=='GET':
        contexto={'obj':prod}
    
    if request.method=='POST':
        prod.estado=False
        prod.save()
        return redirect("inv:producto_list")

    return render(request,template_name,contexto)


# =====================================================================
# Homologacion de Productos ante el SIN (obligacion normativa,
# RND 102500000018). Vincula cada Producto local con su codigo real de
# actividad economica y de producto/servicio SIN, usando el catalogo
# PRODUCTOS_SERVICIOS ya sincronizado en app.catalogos.
# =====================================================================

@login_required(login_url='/login/')
@permission_required('inv.change_producto', login_url='bases:sin_privilegios')
def producto_homologar(request, id):
    """
    Pantalla para asignar a un Producto su actividad economica SIN y su
    codigo de producto/servicio SIN. El select de actividad se llena con
    las actividades distintas presentes en el catalogo PRODUCTOS_SERVICIOS
    ya sincronizado; el select de producto se filtra con JavaScript propio
    (no con el plugin jquery.chained -- tiene incompatibilidades conocidas
    con versiones modernas de jQuery, ver issue #70 del repo del plugin).
    """
    from catalogos.models import CatalogoSIN

    template_name = "inv/producto_homologar.html"
    prod = Producto.objects.filter(pk=id).first()
    if not prod:
        messages.error(request, 'Producto no existe.')
        return redirect('inv:producto_list')

    productos_sin = CatalogoSIN.objects.filter(
        tipo_catalogo=CatalogoSIN.TipoCatalogo.PRODUCTOS_SERVICIOS, vigente=True
    ).exclude(codigo_actividad__isnull=True).order_by('codigo_actividad', 'descripcion')

    if not productos_sin.exists():
        messages.error(
            request,
            'El catálogo de Productos/Servicios del SIN todavía no está sincronizado '
            '(o no trajo datos). Ejecute la sincronización de catálogos antes de homologar.'
        )
        return redirect('inv:producto_list')

    actividades_codigos = list(
        productos_sin.values_list('codigo_actividad', flat=True).distinct()
    )
    actividades = CatalogoSIN.objects.filter(
        tipo_catalogo=CatalogoSIN.TipoCatalogo.ACTIVIDADES,
        codigo__in=actividades_codigos,
        vigente=True,
    ).order_by('descripcion')
    codigos_con_descripcion = set(actividades.values_list('codigo', flat=True))
    actividades_faltantes = [c for c in actividades_codigos if c not in codigos_con_descripcion]

    if request.method == 'POST':
        actividad = request.POST.get('actividad_economica_sin')
        producto_sin_id = request.POST.get('codigo_producto_sin')

        if not actividad or not producto_sin_id:
            messages.error(request, 'Debe seleccionar actividad y producto/servicio SIN.')
            return redirect('inv:producto_homologar', id=id)

        item_sin = productos_sin.filter(codigo=producto_sin_id, codigo_actividad=actividad).first()
        if not item_sin:
            messages.error(request, 'La combinación seleccionada no es válida.')
            return redirect('inv:producto_homologar', id=id)

        prod.actividad_economica_sin = actividad
        prod.codigo_producto_sin = item_sin.codigo
        prod.save()

        messages.success(
            request,
            f'Producto "{prod.descripcion}" homologado: actividad {actividad}, '
            f'producto SIN {item_sin.codigo} - {item_sin.descripcion}.'
        )
        return redirect('inv:producto_list')

    # Datos para el filtrado en JavaScript (ver json_script en el template) --
    # se arma como lista simple de diccionarios, no el queryset directo,
    # para que Django lo pueda serializar a JSON sin problema.
    productos_sin_data = [
        {
            "codigo": item.codigo,
            "actividad": item.codigo_actividad,
            "descripcion": item.descripcion[:90],
        }
        for item in productos_sin
    ]

    return render(request, template_name, {
        'producto': prod,
        'actividades': actividades,
        'actividades_faltantes': actividades_faltantes,
        'productos_sin_data': productos_sin_data,
    })

@login_required(login_url='/login/')
def producto_homologar_pendientes(request):
    """
    Lista rapida de que productos activos todavia NO estan homologados
    (les falta actividad, codigo de producto SIN, o su unidad de medida
    no tiene codigo_sin) -- para que sea facil ver de un vistazo cuanto
    falta, sin tener que revisar producto por producto en el listado
    general.
    """
    productos = Producto.objects.filter(estado=True).select_related('unidad_medida')
    pendientes = [p for p in productos if not p.homologado_sin]
    return render(request, 'inv/producto_homologar_pendientes.html', {
        'pendientes': pendientes,
        'total_productos': productos.count(),
        'total_pendientes': len(pendientes),
    })