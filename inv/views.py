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

    # def form_valid(self, form):
    #     form.instance.uc = self.request.user
    #     self.request.session['success_message'] = self.success_message
    #     return super().form_valid(form)

    def form_valid(self, form):
        form.instance.uc = self.request.user
        self.request.session['success_message'] = self.success_message

        # Obtener la URL de redirección
        redirect_url = reverse_lazy("inv:producto_list")

        # Crear una respuesta JSON con la URL de redirección y el mensaje de éxito
        response = JsonResponse({'redirect_url': redirect_url, 'success_message': self.success_message}, status=200)

        # Establecer el encabezado X-Redirect para indicar al navegador que debe redirigir a la URL especificada
        response['X-Redirect'] = redirect_url

        return super().form_valid(form)
    
    def get_context_data(self, **kwargs): #Aqui se declara que esta función va heredad de la clase producto new
        context = super(ProductoNew, self).get_context_data(**kwargs)
        context["categorias"] = Categoria.objects.all() #Aqui se agregar a la variable contexto la categoria
        context["subcategorias"] = SubCategoria.objects.all() #Aqui se agregar a la variable contexto la categoria
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
    
    def get_context_data(self, **kwargs): #Aqui se declara que esta función va heredad de la clase producto new
        pk = self.kwargs.get('pk')
        
        context = super(ProductoEdit, self).get_context_data(**kwargs)
        context["categorias"] = Categoria.objects.all() #Aqui se agregar a la variable contexto la categoria
        context["subcategorias"] = SubCategoria.objects.all() #Aqui se agregar a la variable contexto la categoria
        context["obj"] = Producto.objects.filter(pk=pk).first()

        return context

@login_required(login_url='/login/')
@permission_required('inv.change_producto',login_url='bases:sin_privilegios')    
def producto_inactivar(request, id):
   prod = Producto.objects.filter(pk=id).first() #Una consulta a la base de datos mediante el ORM de django.
   contexto={} #El contexto esta vacio para poder rellenar
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